from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CameraConfig:
    backend: str = "auto"
    width: int = 1920
    height: int = 1080
    preview_width: int = 640
    preview_height: int = 360
    fps: int = 30
    bitrate: int = 12_000_000
    opencv_device: int = 0
    opencv_fourcc: str = "MJPG"


@dataclass(frozen=True)
class BarcodeConfig:
    scan_every_n_frames: int = 5
    min_chars: int = 4
    max_chars: int = 64
    accepted_pattern: str = r"^[A-Za-z0-9_.-]+$"


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
    enabled: bool = True
    gpio_pin: int = 18
    duration_seconds: float = 0.12


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
    upload: UploadConfig = field(default_factory=UploadConfig)
    paths: Paths = field(default_factory=lambda: Paths.from_root(Path("data")))


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)

    recording = _build_recording(raw.get("recording", {}))
    paths = Paths.from_root(recording.root_dir)

    return AppConfig(
        camera=_dataclass_from_dict(CameraConfig, raw.get("camera", {})),
        barcode=_dataclass_from_dict(BarcodeConfig, raw.get("barcode", {})),
        motion=_build_motion(raw.get("motion", {})),
        recording=recording,
        privacy=_build_privacy(raw.get("privacy", {})),
        sound=_dataclass_from_dict(SoundConfig, raw.get("sound", {})),
        upload=_dataclass_from_dict(UploadConfig, raw.get("upload", {})),
        paths=paths,
    )


def _build_recording(raw: dict[str, Any]) -> RecordingConfig:
    values = dict(raw)
    if "root_dir" in values:
        values["root_dir"] = Path(values["root_dir"])
    return _dataclass_from_dict(RecordingConfig, values)


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


def _roi_tuple(value: Any) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError(f"ROI/mask must contain 4 values, got {value!r}")
    result = tuple(float(part) for part in value)
    x, y, width, height = result
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise ValueError(f"ROI/mask must be normalized inside the image, got {value!r}")
    return result


def _dataclass_from_dict(cls: type[Any], values: dict[str, Any]) -> Any:
    field_names = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    unknown = set(values) - field_names
    if unknown:
        raise ValueError(f"Unknown config keys for {cls.__name__}: {sorted(unknown)}")
    return cls(**values)
