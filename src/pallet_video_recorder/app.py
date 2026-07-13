from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .barcode import BarcodeReader
from .camera import FrameSource, build_frame_source
from .config import AppConfig
from .filenames import build_video_name
from .motion import MotionDetector
from .privacy import PrivacyProcessor
from .sound import Beeper
from .status_light import StatusLight
from .uploader import UploadWorker

LOGGER = logging.getLogger(__name__)


@dataclass
class ActiveRecording:
    order_number: str
    started_at: float
    in_progress_path: Path
    final_name: str
    seen_motion: bool = False


class PalletVideoApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.running = False
        self.frame_source: FrameSource | None = None
        self.upload_worker = UploadWorker(config.upload, config.paths)
        self.barcode_reader = BarcodeReader(config.barcode)
        self.motion_detector = MotionDetector(config.motion)
        self.privacy_processor = PrivacyProcessor(config.privacy)
        self.beeper = Beeper(config.sound)
        self.status_light = StatusLight(config.status_light)

    def run(self) -> None:
        self.config.paths.ensure()
        self.running = True
        self.upload_worker.start()

        self.frame_source = build_frame_source(self.config.camera)
        self.frame_source.start()

        active: ActiveRecording | None = None
        frame_number = 0

        LOGGER.info("Ready for barcode scan")
        self.status_light.idle()
        while self.running:
            frame = self.frame_source.capture_preview()
            if frame is None:
                time.sleep(0.05)
                continue

            frame_number += 1
            self.frame_source.note_frame(frame)

            if active is None:
                order_number = self._read_barcode(frame, frame_number)
                if order_number:
                    active = self._start_recording(order_number)
                    self.motion_detector.reset()
                continue

            sample = self.motion_detector.update(frame)
            if sample.moving:
                active.seen_motion = True

            elapsed = time.monotonic() - active.started_at
            stop_reason = self._stop_reason(active, elapsed, sample.still_for_seconds)
            if stop_reason:
                LOGGER.info(
                    "Stopping recording for order %s after %.1fs: %s",
                    active.order_number,
                    elapsed,
                    stop_reason,
                )
                self._finish_recording(active)
                active = None
                self.motion_detector.reset()
                LOGGER.info("Ready for next barcode scan")
                self.status_light.idle()

        if active is not None:
            LOGGER.info("Application stopping with active recording; finalizing it")
            self._finish_recording(active)

        self._close()

    def stop(self) -> None:
        self.running = False

    def _close(self) -> None:
        self.upload_worker.stop()
        if self.frame_source is not None:
            self.frame_source.close()
        self.beeper.close()
        self.status_light.close()

    def _read_barcode(self, frame: object, frame_number: int) -> str | None:
        if frame_number % self.config.barcode.scan_every_n_frames != 0:
            return None

        barcode = self.barcode_reader.read(frame)
        if not barcode:
            return None

        LOGGER.info("Read barcode/order number: %s", barcode)
        self.beeper.beep()
        self.status_light.scanned()
        return barcode

    def _start_recording(self, order_number: str) -> ActiveRecording:
        final_name = build_video_name(order_number, self.config.recording.file_extension)
        in_progress_path = self.config.paths.in_progress / final_name
        LOGGER.info("Starting recording for order %s to %s", order_number, in_progress_path)

        assert self.frame_source is not None
        self.frame_source.start_recording(in_progress_path)
        self.status_light.recording()
        return ActiveRecording(
            order_number=order_number,
            started_at=time.monotonic(),
            in_progress_path=in_progress_path,
            final_name=final_name,
        )

    def _stop_reason(
        self,
        active: ActiveRecording,
        elapsed_seconds: float,
        still_for_seconds: float,
    ) -> str | None:
        motion = self.config.motion
        if elapsed_seconds >= motion.maximum_recording_seconds:
            return "maximum recording time reached"

        if elapsed_seconds < motion.minimum_recording_seconds:
            return None

        if motion.require_motion_before_stop and not active.seen_motion:
            return None

        if still_for_seconds >= motion.still_seconds:
            return "pallet appears still"

        return None

    def _finish_recording(self, active: ActiveRecording) -> None:
        assert self.frame_source is not None
        self.frame_source.stop_recording()

        pending_path = self.config.paths.pending / active.final_name
        source_for_upload = active.in_progress_path

        if self.config.privacy.enabled:
            try:
                processed_path = self.privacy_processor.process(active.in_progress_path, pending_path)
                if processed_path != active.in_progress_path:
                    source_for_upload = processed_path
            except Exception:
                LOGGER.exception("Privacy processing failed; moving recording to failed folder")
                failed_path = self.config.paths.failed / active.final_name
                if pending_path.exists():
                    pending_path.unlink()
                if active.in_progress_path.exists():
                    shutil.move(str(active.in_progress_path), str(failed_path))
                return
        else:
            shutil.move(str(active.in_progress_path), str(pending_path))
            source_for_upload = pending_path

        if source_for_upload.parent != self.config.paths.pending:
            shutil.move(str(source_for_upload), str(pending_path))

        self.upload_worker.wake()
