from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .camera import FrameSource, build_frame_source
from .cloud import SupabaseDeviceClient
from .config import AppConfig
from .filenames import build_video_name
from .hardware_scanner import HardwareScannerWorker
from .log_safety import safe_scan_value
from .motion import MotionDetector
from .privacy import PrivacyProcessor
from .preview import CameraPreviewServer
from .provisioning import (
    DeviceIdentity,
    DeviceIdentityStore,
    ProvisioningError,
    looks_like_provisioning_qr,
    parse_reset_qr,
    parse_provisioning_qr,
)
from .scanner import BarcodeScanWorker
from .scanner_schedule import ScannerSchedule
from .sound import Beeper
from .software_update import SoftwareUpdateWorker
from .status_light import StatusLight
from .uploader import UploadWorker, sidecar_path

LOGGER = logging.getLogger(__name__)


@dataclass
class ActiveRecording:
    scanned_id: str
    started_at: float
    started_wall_time: datetime
    in_progress_path: Path
    final_name: str
    seen_motion: bool = False


class PalletVideoApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.running = False
        self.frame_source: FrameSource | None = None
        self.cloud_client = SupabaseDeviceClient(config.cloud, config.paths)
        self.upload_worker = UploadWorker(
            config.upload,
            config.paths,
            cloud_client=self.cloud_client,
            identity_provider=lambda: self.device_identity,
        )
        self.hardware_scanner = HardwareScannerWorker(config.hardware_scanner)
        self.barcode_scanner = BarcodeScanWorker(config.barcode)
        self.motion_detector = MotionDetector(config.motion)
        self.privacy_processor = PrivacyProcessor(config.privacy)
        self.preview_server = CameraPreviewServer(config.preview)
        self.software_updater = SoftwareUpdateWorker(config.software_update, config.paths)
        self.beeper = Beeper(config.sound)
        self.status_light = StatusLight(config.status_light)
        self._last_scan_status_logged_at = 0.0
        self._last_heartbeat_at = 0.0
        self._cloud_activation_confirmed = False
        self.scanner_schedule = ScannerSchedule()
        self._scanner_awake: bool | None = None
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
        self._send_cloud_heartbeat("online", force=True)
        self._sync_scanner_trigger()
        while self.running:
            frame = self.frame_source.capture_preview()
            if frame is None:
                time.sleep(0.05)
                continue

            frame_number += 1
            self.frame_source.note_frame(frame)
            self.preview_server.update_frame(frame)

            if active is None:
                self._send_cloud_heartbeat("online")
                idle_seconds = time.monotonic() - idle_since
                scanner_awake = self._sync_scanner_trigger()
                if self.software_updater.ready_to_apply(idle_seconds):
                    self.hardware_scanner.disable_triggering()
                    if self.software_updater.apply_pending():
                        self.running = False
                    else:
                        self._sync_scanner_trigger()
                    continue

                self._log_scan_status(frame_number)
                if not scanner_awake:
                    self.hardware_scanner.discard_pending_results()
                    continue

                scanned_id = self._read_scanned_id(frame, frame_number)
                if scanned_id:
                    self.hardware_scanner.disable_triggering()
                    active = self._start_recording(scanned_id)
                    self._send_cloud_heartbeat("recording", force=True)
                    idle_since = 0.0
                    self.motion_detector.reset()
                continue

            self._send_cloud_heartbeat("recording")
            sample = self.motion_detector.update(frame)
            if sample.moving:
                active.seen_motion = True

            elapsed = time.monotonic() - active.started_at
            stop_reason = self._stop_reason(active, elapsed, sample.still_for_seconds)
            if stop_reason:
                LOGGER.info(
                    "Stopping recording for scanned ID %s after %.1fs: %s",
                    active.scanned_id,
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
                self._send_cloud_heartbeat("online", force=True)
                self._sync_scanner_trigger()

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
            self._activate_cloud_identity(identity)
            return identity

        return None

    def _read_scanned_id(self, frame: object, frame_number: int) -> str | None:
        barcode = self.hardware_scanner.poll()
        if barcode:
            if self._handle_reset_qr(barcode):
                return None
            if looks_like_provisioning_qr(
                barcode,
                prefix=self.config.device.provisioning_qr_prefix,
            ):
                LOGGER.warning("Ignoring provisioning QR scan after device is already provisioned")
                return None
            LOGGER.info("Read scanned ID from hardware scanner: %s", barcode)
            self.beeper.beep()
            self.status_light.scanned()
            return barcode

        if not self.config.barcode.enabled:
            return None

        barcode = self.barcode_scanner.poll()
        if barcode:
            if self._handle_reset_qr(barcode):
                return None
            if looks_like_provisioning_qr(
                barcode,
                prefix=self.config.device.provisioning_qr_prefix,
            ):
                LOGGER.warning("Ignoring provisioning QR scan after device is already provisioned")
                return None
            LOGGER.info("Read scanned ID from camera: %s", barcode)
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
                safe_scan_value(hardware_stats.last_result),
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
            safe_scan_value(stats.last_result),
        )

    def _start_recording(self, scanned_id: str) -> ActiveRecording:
        assert self.device_identity is not None
        final_name = build_video_name(
            scanned_id,
            self.config.recording.file_extension,
            serial_number=self.device_identity.serial_number,
        )
        in_progress_path = self.config.paths.in_progress / final_name
        LOGGER.info("Starting recording for scanned ID %s to %s", scanned_id, in_progress_path)

        assert self.frame_source is not None
        self.frame_source.start_recording(in_progress_path)
        self.status_light.recording()
        return ActiveRecording(
            scanned_id=scanned_id,
            started_at=time.monotonic(),
            started_wall_time=datetime.now(timezone.utc),
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

        self._write_video_sidecar(active, pending_path)
        self.upload_worker.wake()

    def _identity_path(self) -> Path:
        path = self.config.device.identity_file
        if path.is_absolute():
            return path
        return self.config.paths.root / path

    def _send_cloud_heartbeat(self, status: str, *, force: bool = False) -> None:
        if self.device_identity is None:
            return
        now = time.monotonic()
        if not force and now - self._last_heartbeat_at < self.config.cloud.heartbeat_interval_seconds:
            return
        self._last_heartbeat_at = now

        if not self._cloud_activation_confirmed:
            self._activate_cloud_identity(self.device_identity)
            if not self._cloud_activation_confirmed:
                return

        result = self.cloud_client.heartbeat(
            self.device_identity,
            status=status,
            software_version=__version__,
            last_update_id=self._last_applied_update_id(),
            metadata={
                **self.cloud_client.build_metadata(),
                "scanner_awake": bool(self._scanner_awake if self._scanner_awake is not None else self.scanner_schedule.is_active()),
                "scanner_schedule_enabled": self.scanner_schedule.enabled,
            },
        )
        if result.ok:
            self._apply_cloud_config(result.data)
            LOGGER.info("Device heartbeat sent status=%s", status)

    def _activate_cloud_identity(self, identity: DeviceIdentity) -> None:
        result = self.cloud_client.activate(
            identity,
            software_version=__version__,
            metadata=self.cloud_client.build_metadata(),
        )
        if result.ok:
            self._apply_cloud_config(result.data)
            self._cloud_activation_confirmed = True
            LOGGER.info("Device activation confirmed by Supabase")

    def _apply_cloud_config(self, data: dict[str, object] | None) -> None:
        if not data:
            return
        next_schedule = ScannerSchedule.from_cloud(data.get("scanner_schedule"))
        if next_schedule != self.scanner_schedule:
            self.scanner_schedule = next_schedule
            self._scanner_awake = None
            LOGGER.info(
                "Scanner schedule updated enabled=%s active=%s-%s days=%s timezone=%s",
                next_schedule.enabled,
                next_schedule.active_start.strftime("%H:%M"),
                next_schedule.active_end.strftime("%H:%M"),
                ",".join(str(day) for day in next_schedule.active_days),
                next_schedule.timezone,
            )

    def _sync_scanner_trigger(self) -> bool:
        scanner_awake = self.scanner_schedule.is_active()
        if scanner_awake:
            self.hardware_scanner.enable_triggering()
        else:
            self.hardware_scanner.disable_triggering()

        if scanner_awake != self._scanner_awake:
            LOGGER.info("Scanner schedule state changed: %s", "active" if scanner_awake else "sleeping")
            self._scanner_awake = scanner_awake
        return scanner_awake

    def _last_applied_update_id(self) -> str:
        try:
            state = self.software_updater.state_store.load()
        except Exception:
            return ""
        return str(state.get("applied_update_id", ""))

    def _write_video_sidecar(self, active: ActiveRecording, pending_path: Path) -> None:
        ended_at = datetime.now(timezone.utc)
        metadata = {
            "schema_version": 1,
            "scanned_id": active.scanned_id,
            "filename": pending_path.name,
            "started_at": _format_datetime(active.started_wall_time),
            "ended_at": _format_datetime(ended_at),
            "duration_seconds": round(time.monotonic() - active.started_at, 2),
            "privacy_enabled": self.config.privacy.enabled,
        }
        path = sidecar_path(pending_path)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def _handle_reset_qr(self, raw_value: str) -> bool:
        assert self.device_identity is not None
        try:
            payload = parse_reset_qr(raw_value, prefix=self.config.device.provisioning_qr_prefix)
        except ProvisioningError:
            return False

        if payload.serial_number != self.device_identity.serial_number:
            LOGGER.warning(
                "Ignoring reset QR for serial %s on device %s",
                payload.serial_number,
                self.device_identity.serial_number,
            )
            return True

        LOGGER.warning("Reset QR accepted for device serial %s; deleting local identity", self.device_identity.serial_number)
        self.cloud_client.device_event(
            self.device_identity,
            event_type="device_reset_requested",
            severity="warning",
            message="Device reset QR scanned; local identity will be removed",
            metadata={"serial_number": self.device_identity.serial_number},
        )
        self.identity_store.delete()
        self._cloud_activation_confirmed = False
        self.device_identity = None
        self.running = False
        self.status_light.scanned()
        self.beeper.beep()
        return True


def _seconds_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}s"


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
