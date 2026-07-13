from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class CameraConfig:
    backend: str = "auto"
    width: int = 1920
    height: int = 1080
    preview_width: int = 1280
    preview_height: int = 720
    fps: int = 30
    bitrate: int = 12_000_000
    opencv_device: int = 0
    opencv_fourcc: str = "MJPG"
    autofocus_mode: str = "continuous"


@dataclass(frozen=True)
class BarcodeConfig:
    scan_every_n_frames: int = 1
    min_chars: int = 4
    max_chars: int = 64
    accepted_pattern: str = r"^[A-Za-z0-9_.()-]+$"
    roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    rotation_degrees: tuple[int, ...] = (
        0,
        90,
        180,
        270,
        15,
        345,
        30,
        330,
        45,
        315,
        60,
        300,
        75,
        285,
        105,
        255,
        120,
        240,
        135,
        225,
        150,
        210,
        165,
        195,
    )
    scan_scales: tuple[float, ...] = (1.0, 1.5)
    preprocess: bool = True
    confirm_read_count: int = 2
    confirm_window_seconds: float = 1.5
    duplicate_suppress_seconds: float = 8.0
    ambient_suppress_seconds: float = 2.0
    ambient_absent_seconds: float = 2.0
    validate_gs1_ai01_check_digit: bool = True


@dataclass(frozen=True)
class MotionConfig:
    roi: tuple[float, float, float, float] = (0.08, 0.08, 0.84, 0.84)
    threshold: float = 0.018
    still_seconds: float = 4.0
    minimum_recording_seconds: float = 8.0
    maximum_recording_seconds: float = 180.0
    require_motion_before_stop: bool = True


@dataclass(frozen=True)
class RecordingConfig:
    root_dir: Path = Path("data")
    file_extension: str = ".mp4"


@dataclass(frozen=True)
class PrivacyConfig:
    enabled: bool = False
    face_blur: bool = True
    delete_source_after_processing: bool = True
    fixed_masks: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class SoundConfig:
    enabled: bool = False
    gpio_pin: int = 18
    duration_seconds: float = 0.12


@dataclass(frozen=True)
class StatusLightConfig:
    enabled: bool = True
    backend: str = "gpio"
    red_gpio_pin: int = 27
    green_gpio_pin: int = 17
    yellow_gpio_pin: int | None = None
    active_high: bool = True
    scan_flash_seconds: float = 0.4
    sysfs_led_name: str = "ACT"
    restore_trigger: str = "mmc0"


@dataclass(frozen=True)
class UploadConfig:
    enabled: bool = True
    protocol: str = "sftp"
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    remote_dir: str = "/"
    passive: bool = True
    timeout_seconds: int = 30
    retry_seconds: int = 20
    delete_after_upload: bool = False
    temp_suffix: str = ".part"


@dataclass(frozen=True)
class Paths:
    root: Path
    in_progress: Path
    pending: Path
    uploaded: Path
    failed: Path

    @classmethod
    def from_root(cls, root: Path) -> "Paths":
        return cls(
            root=root,
            in_progress=root / "in-progress",
            pending=root / "pending",
            uploaded=root / "uploaded",
            failed=root / "failed",
        )

    def ensure(self) -> None:
        for path in (self.root, self.in_progress, self.pending, self.uploaded, self.failed):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    barcode: BarcodeConfig = field(default_factory=BarcodeConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    sound: SoundConfig = field(default_factory=SoundConfig)
    status_light: StatusLightConfig = field(default_factory=StatusLightConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    paths: Paths = field(default_factory=lambda: Paths.from_root(Path("data")))


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)

    recording = _build_recording(raw.get("recording", {}))
    paths = Paths.from_root(recording.root_dir)

    return AppConfig(
        camera=_dataclass_from_dict(CameraConfig, raw.get("camera", {})),
        barcode=_build_barcode(raw.get("barcode", {})),
        motion=_build_motion(raw.get("motion", {})),
        recording=recording,
        privacy=_build_privacy(raw.get("privacy", {})),
        sound=_dataclass_from_dict(SoundConfig, raw.get("sound", {})),
        status_light=_build_status_light(raw.get("status_light", {})),
        upload=_dataclass_from_dict(UploadConfig, raw.get("upload", {})),
        paths=paths,
    )


def _build_recording(raw: dict[str, Any]) -> RecordingConfig:
    values = dict(raw)
    if "root_dir" in values:
        values["root_dir"] = Path(values["root_dir"])
    return _dataclass_from_dict(RecordingConfig, values)


def _build_barcode(raw: dict[str, Any]) -> BarcodeConfig:
    values = dict(raw)
    if "roi" in values:
        values["roi"] = _roi_tuple(values["roi"])
    if "rotation_degrees" in values:
        values["rotation_degrees"] = _int_tuple(values["rotation_degrees"], "rotation_degrees")
    if "scan_scales" in values:
        values["scan_scales"] = _positive_float_tuple(values["scan_scales"], "scan_scales")

    config = _dataclass_from_dict(BarcodeConfig, values)
    if config.scan_every_n_frames < 1:
        raise ValueError("barcode.scan_every_n_frames must be at least 1")
    if config.min_chars < 1 or config.max_chars < config.min_chars:
        raise ValueError("barcode min/max character limits are invalid")
    if config.confirm_read_count < 1:
        raise ValueError("barcode.confirm_read_count must be at least 1")
    if config.confirm_window_seconds <= 0:
        raise ValueError("barcode.confirm_window_seconds must be positive")
    if config.duplicate_suppress_seconds < 0:
        raise ValueError("barcode.duplicate_suppress_seconds cannot be negative")
    if config.ambient_suppress_seconds < 0:
        raise ValueError("barcode.ambient_suppress_seconds cannot be negative")
    if config.ambient_absent_seconds <= 0:
        raise ValueError("barcode.ambient_absent_seconds must be positive")
    return config


def _build_motion(raw: dict[str, Any]) -> MotionConfig:
    values = dict(raw)
    if "roi" in values:
        values["roi"] = _roi_tuple(values["roi"])
    return _dataclass_from_dict(MotionConfig, values)


def _build_privacy(raw: dict[str, Any]) -> PrivacyConfig:
    values = dict(raw)
    if "fixed_masks" in values:
        values["fixed_masks"] = tuple(_roi_tuple(mask) for mask in values["fixed_masks"])
    return _dataclass_from_dict(PrivacyConfig, values)


def _build_status_light(raw: dict[str, Any]) -> StatusLightConfig:
    config = _dataclass_from_dict(StatusLightConfig, raw)
    if config.backend not in {"gpio", "act_led"}:
        raise ValueError("status_light.backend must be 'gpio' or 'act_led'")
    if config.scan_flash_seconds < 0:
        raise ValueError("status_light.scan_flash_seconds cannot be negative")
    pins = [config.red_gpio_pin, config.green_gpio_pin]
    if config.yellow_gpio_pin is not None:
        pins.append(config.yellow_gpio_pin)
    if len(set(pins)) != len(pins):
        raise ValueError("status_light GPIO pins must be different")
    _validate_sysfs_token(config.sysfs_led_name, "status_light.sysfs_led_name")
    _validate_sysfs_token(config.restore_trigger, "status_light.restore_trigger")
    return config


def _roi_tuple(value: Any) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError(f"ROI/mask must contain 4 values, got {value!r}")
    result = tuple(float(part) for part in value)
    x, y, width, height = result
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise ValueError(f"ROI/mask must be normalized inside the image, got {value!r}")
    return result


def _int_tuple(value: Any, name: str) -> tuple[int, ...]:
    if not value:
        raise ValueError(f"{name} must contain at least one value")
    return tuple(int(part) for part in value)


def _positive_float_tuple(value: Any, name: str) -> tuple[float, ...]:
    if not value:
        raise ValueError(f"{name} must contain at least one value")
    result = tuple(float(part) for part in value)
    if any(part <= 0 for part in result):
        raise ValueError(f"{name} values must be positive")
    return result


def _validate_sysfs_token(value: str, name: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9:_-]+", value) is None:
        raise ValueError(f"{name} may only contain letters, numbers, colon, underscore or dash")


def _dataclass_from_dict(cls: type[Any], values: dict[str, Any]) -> Any:
    field_names = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    unknown = set(values) - field_names
    if unknown:
        raise ValueError(f"Unknown config keys for {cls.__name__}: {sorted(unknown)}")
    return cls(**values)
