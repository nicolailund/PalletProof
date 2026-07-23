from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .camera import FrameSource, build_frame_source
from .config import AppConfig
from .filenames import build_video_name
from .hardware_scanner import HardwareScannerWorker
from .motion import MotionDetector
from .privacy import PrivacyProcessor
from .preview import CameraPreviewServer
from .provisioning import (
    DeviceIdentity,
    DeviceIdentityStore,
    ProvisioningError,
    looks_like_provisioning_qr,
    parse_provisioning_qr,
)
from .scanner import BarcodeScanWorker
from .sound import Beeper
from .software_update import SoftwareUpdateWorker
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
        self.hardware_scanner = HardwareScannerWorker(config.hardware_scanner)
        self.barcode_scanner = BarcodeScanWorker(config.barcode)
        self.motion_detector = MotionDetector(config.motion)
        self.privacy_processor = PrivacyProcessor(config.privacy)
        self.preview_server = CameraPreviewServer(config.preview)
        self.software_updater = SoftwareUpdateWorker(config.software_update, config.paths)
        self.beeper = Beeper(config.sound)
        self.status_light = StatusLight(config.status_light)
        self._last_scan_status_logged_at = 0.0
        self.identity_store = DeviceIdentityStore(self._identity_path())
        self.device_identity: DeviceIdentity | None = None

    def run(self) -> None:
        self.config.paths.ensure()
        self.running = True
        self.hardware_scanner.start()
        self.status_light.idle()

        self.device_identity = self._load_or_wait_for_device_identity()
        if self.device_identity is None:
            LOGGER.info("Application stopped before device was provisioned")
            self._close()
            return

        self.upload_worker.start()
        self.software_updater.start()
        self.preview_server.start()
        if self.config.barcode.enabled:
            self.barcode_scanner.start()
        else:
            LOGGER.info("Camera barcode scanner disabled; waiting for hardware scanner input")

        self.frame_source = build_frame_source(self.config.camera)
        self.frame_source.start()

        active: ActiveRecording | None = None
        idle_since = time.monotonic()
        frame_number = 0

        LOGGER.info("Ready for barcode scan on device serial %s", self.device_identity.serial_number)
        self.status_light.idle()
        self.hardware_scanner.enable_triggering()
        while self.running:
            frame = self.frame_source.capture_preview()
            if frame is None:
                time.sleep(0.05)
                continue

            frame_number += 1
            self.frame_source.note_frame(frame)
            self.preview_server.update_frame(frame)

            if active is None:
                idle_seconds = time.monotonic() - idle_since
                if self.software_updater.ready_to_apply(idle_seconds):
                    self.hardware_scanner.disable_triggering()
                    if self.software_updater.apply_pending():
                        self.running = False
                    else:
                        self.hardware_scanner.enable_triggering()
                    continue

                self._log_scan_status(frame_number)
                order_number = self._read_order_number(frame, frame_number)
                if order_number:
                    self.hardware_scanner.disable_triggering()
                    active = self._start_recording(order_number)
                    idle_since = 0.0
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
                idle_since = time.monotonic()
                self.motion_detector.reset()
                if self.config.barcode.enabled:
                    self.barcode_scanner.start_ambient_suppression()
                LOGGER.info("Ready for next barcode scan")
                self.status_light.idle()
                self.hardware_scanner.enable_triggering()

        if active is not None:
            LOGGER.info("Application stopping with active recording; finalizing it")
            self._finish_recording(active)

        self._close()

    def stop(self) -> None:
        self.running = False

    def _close(self) -> None:
        self.upload_worker.stop()
        self.software_updater.stop()
        self.preview_server.stop()
        self.hardware_scanner.disable_triggering()
        self.hardware_scanner.stop()
        self.barcode_scanner.stop()
        if self.frame_source is not None:
            self.frame_source.close()
        self.beeper.close()
        self.status_light.close()

    def _load_or_wait_for_device_identity(self) -> DeviceIdentity | None:
        try:
            identity = self.identity_store.load()
        except Exception:
            LOGGER.exception("Could not load device identity")
            raise

        if identity is not None:
            LOGGER.info(
                "Device identity loaded serial=%s customer=%s site=%s",
                identity.serial_number,
                identity.customer_id or "-",
                identity.site_id or "-",
            )
            return identity

        if not self.config.device.provisioning_required:
            identity = DeviceIdentity.unmanaged(self.config.device.serial_number)
            LOGGER.warning(
                "Device provisioning disabled; using unmanaged serial %s",
                identity.serial_number,
            )
            return identity

        if not self.config.hardware_scanner.enabled:
            LOGGER.error("Device is unprovisioned, but hardware scanner is disabled")
            return None

        LOGGER.warning("Device is unprovisioned; waiting for PalletProof provisioning QR")
        self.hardware_scanner.enable_triggering()
        while self.running:
            raw_value = self.hardware_scanner.poll()
            if raw_value is None:
                time.sleep(0.1)
                continue

            try:
                payload = parse_provisioning_qr(
                    raw_value,
                    prefix=self.config.device.provisioning_qr_prefix,
                    now=datetime.now(timezone.utc),
                )
            except ProvisioningError as exc:
                LOGGER.warning("Ignoring scan while unprovisioned; provisioning QR required: %s", exc)
                continue

            identity = payload.to_identity()
            self.identity_store.save(identity)
            self.hardware_scanner.disable_triggering()
            self.beeper.beep()
            self.status_light.scanned()
            LOGGER.info(
                "Device provisioned serial=%s customer=%s site=%s wifi_ssid=%s api_base_url=%s",
                identity.serial_number,
                identity.customer_id or "-",
                identity.site_id or "-",
                identity.wifi_ssid or "-",
                identity.api_base_url or "-",
            )
            return identity

        return None

    def _read_order_number(self, frame: object, frame_number: int) -> str | None:
        barcode = self.hardware_scanner.poll()
        if barcode:
            if looks_like_provisioning_qr(
                barcode,
                prefix=self.config.device.provisioning_qr_prefix,
            ):
                LOGGER.warning("Ignoring provisioning QR scan after device is already provisioned")
                return None
            LOGGER.info("Read barcode/order number from hardware scanner: %s", barcode)
            self.beeper.beep()
            self.status_light.scanned()
            return barcode

        if not self.config.barcode.enabled:
            return None

        barcode = self.barcode_scanner.poll()
        if barcode:
            LOGGER.info("Read barcode/order number from camera: %s", barcode)
            self.beeper.beep()
            self.status_light.scanned()
            return barcode

        if frame_number % self.config.barcode.scan_every_n_frames != 0:
            return None

        self.barcode_scanner.submit(frame)
        return None

    def _log_scan_status(self, frame_number: int) -> None:
        now = time.monotonic()
        if now - self._last_scan_status_logged_at < 10.0:
            return
        self._last_scan_status_logged_at = now
        hardware_stats = self.hardware_scanner.stats()
        if not self.config.barcode.enabled:
            LOGGER.info(
                "SCAN_STATUS frames=%s hardware_connected=%s hardware_device=%s hardware_reads=%s hardware_queued=%s hardware_last=%s camera_scanner=disabled",
                frame_number,
                hardware_stats.connected,
                hardware_stats.device or "-",
                hardware_stats.read_count,
                hardware_stats.queued_results,
                hardware_stats.last_result or "-",
            )
            return

        stats = self.barcode_scanner.stats()
        LOGGER.info(
            "BARCODE_SCAN_STATUS frames=%s hardware_connected=%s hardware_device=%s hardware_reads=%s hardware_queued=%s submitted=%s completed=%s busy=%s current=%s last=%s queued=%s last_result=%s",
            frame_number,
            hardware_stats.connected,
            hardware_stats.device or "-",
            hardware_stats.read_count,
            hardware_stats.queued_results,
            stats.submitted_count,
            stats.completed_count,
            stats.busy,
            _seconds_text(stats.current_elapsed_seconds),
            _seconds_text(stats.last_duration_seconds),
            stats.queued_results,
            stats.last_result or "-",
        )

    def _start_recording(self, order_number: str) -> ActiveRecording:
        assert self.device_identity is not None
        final_name = build_video_name(
            order_number,
            self.config.recording.file_extension,
            serial_number=self.device_identity.serial_number,
        )
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

    def _identity_path(self) -> Path:
        path = self.config.device.identity_file
        if path.is_absolute():
            return path
        return self.config.paths.root / path


def _seconds_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}s"
