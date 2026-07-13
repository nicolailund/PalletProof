from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Protocol

from .config import CameraConfig

LOGGER = logging.getLogger(__name__)


class FrameSource(Protocol):
    def start(self) -> None:
        ...

    def capture_preview(self) -> Any | None:
        ...

    def start_recording(self, output_path: Path) -> None:
        ...

    def note_frame(self, frame: Any) -> None:
        ...

    def stop_recording(self) -> None:
        ...

    def close(self) -> None:
        ...


def build_frame_source(config: CameraConfig) -> FrameSource:
    if config.backend == "auto":
        camera_num = _picamera2_csi_camera_num()
        if camera_num is not None:
            LOGGER.info("Auto camera selection chose Picamera2/CSI camera %s", camera_num)
            return PiCamera2FrameSource(config, camera_num=camera_num)
        LOGGER.info("Auto camera selection found no CSI camera; using OpenCV/USB camera")
        return OpenCvFrameSource(config)
    if config.backend == "picamera2":
        return PiCamera2FrameSource(config)
    if config.backend == "opencv":
        return OpenCvFrameSource(config)
    raise ValueError(f"Unsupported camera backend: {config.backend}")


def _picamera2_csi_camera_num() -> int | None:
    try:
        from picamera2 import Picamera2

        cameras = Picamera2.global_camera_info()
        for camera in cameras:
            if _is_csi_camera_info(camera):
                return int(camera.get("Num", 0))
    except Exception as exc:  # pragma: no cover - host/Pi hardware dependent
        LOGGER.warning("Could not query Picamera2 cameras; falling back to USB/OpenCV: %s", exc)
    return None


def _is_csi_camera_info(camera: dict[str, Any]) -> bool:
    model = str(camera.get("Model", "")).lower()
    camera_id = str(camera.get("Id", "")).lower()
    combined = f"{model} {camera_id}"

    if "usb" in camera_id or "uvc" in combined or "webcam" in model:
        return False

    csi_sensor_tokens = ("imx", "ov")
    return any(token in combined for token in csi_sensor_tokens)


class PiCamera2FrameSource:
    def __init__(self, config: CameraConfig, camera_num: int | None = None) -> None:
        self.config = config
        self.camera_num = camera_num
        self.picam2: Any | None = None

    def start(self) -> None:
        try:
            from picamera2 import Picamera2
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            raise RuntimeError("picamera2 is not available. Install python3-picamera2 on the Pi.") from exc

        if self.camera_num is None:
            self.picam2 = Picamera2()
        else:
            self.picam2 = Picamera2(self.camera_num)
        video_config = self.picam2.create_video_configuration(
            main={"size": (self.config.width, self.config.height)},
            lores={
                "size": (self.config.preview_width, self.config.preview_height),
                "format": "YUV420",
            },
            controls={"FrameRate": self.config.fps},
        )
        self.picam2.configure(video_config)
        self._apply_autofocus()
        self.picam2.start()
        time.sleep(1.0)
        LOGGER.info("Started Picamera2 at %sx%s", self.config.width, self.config.height)

    def capture_preview(self) -> Any | None:
        assert self.picam2 is not None
        frame = self.picam2.capture_array("lores")
        return self._lores_to_bgr(frame)

    def start_recording(self, output_path: Path) -> None:
        assert self.picam2 is not None
        try:
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import FfmpegOutput
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            raise RuntimeError("Picamera2 recording dependencies are missing") from exc

        encoder = H264Encoder(bitrate=self.config.bitrate)
        output = FfmpegOutput(str(output_path))
        self.picam2.start_recording(encoder, output)

    def note_frame(self, frame: Any) -> None:
        return None

    def stop_recording(self) -> None:
        assert self.picam2 is not None
        self.picam2.stop_recording()

    def close(self) -> None:
        if self.picam2 is not None:
            self.picam2.close()
            self.picam2 = None

    def _lores_to_bgr(self, frame: Any) -> Any:
        import cv2

        expected_yuv_height = self.config.preview_height * 3 // 2
        if len(frame.shape) == 2 and frame.shape[0] == expected_yuv_height:
            return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
        return frame

    def _apply_autofocus(self) -> None:
        mode = self.config.autofocus_mode.lower()
        if mode in {"", "default", "off"}:
            return

        try:
            from libcamera import controls
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            LOGGER.warning("Could not import libcamera autofocus controls: %s", exc)
            return

        modes = {
            "manual": controls.AfModeEnum.Manual,
            "auto": controls.AfModeEnum.Auto,
            "continuous": controls.AfModeEnum.Continuous,
        }
        af_mode = modes.get(mode)
        if af_mode is None:
            LOGGER.warning("Unknown autofocus mode %r; leaving camera default", self.config.autofocus_mode)
            return

        assert self.picam2 is not None
        control_values: dict[str, Any] = {"AfMode": af_mode}
        af_range = _enum_control_value(
            controls,
            "AfRangeEnum",
            self.config.autofocus_range,
            {"default", ""},
        )
        if af_range is not None:
            control_values["AfRange"] = af_range
        af_speed = _enum_control_value(
            controls,
            "AfSpeedEnum",
            self.config.autofocus_speed,
            {"default", ""},
        )
        if af_speed is not None:
            control_values["AfSpeed"] = af_speed

        try:
            self.picam2.set_controls(control_values)
            LOGGER.info(
                "Set Picamera2 autofocus controls: mode=%s range=%s speed=%s",
                mode,
                self.config.autofocus_range,
                self.config.autofocus_speed,
            )
        except Exception as exc:  # pragma: no cover - hardware dependent
            LOGGER.warning("Could not set Picamera2 autofocus controls %s: %s", control_values, exc)


def _enum_control_value(
    controls: Any,
    enum_name: str,
    raw_value: str,
    skip_values: set[str],
) -> Any | None:
    value = raw_value.lower()
    if value in skip_values:
        return None

    enum = getattr(controls, enum_name, None)
    if enum is None:
        LOGGER.warning("libcamera controls has no %s; ignoring %s", enum_name, raw_value)
        return None

    for name in dir(enum):
        if name.startswith("_"):
            continue
        if name.lower() == value:
            return getattr(enum, name)

    LOGGER.warning("Unknown %s value %r; ignoring it", enum_name, raw_value)
    return None


class OpenCvFrameSource:
    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.cv2: Any | None = None
        self.capture: Any | None = None
        self.writer: Any | None = None
        self.frame_size: tuple[int, int] | None = None

    def start(self) -> None:
        import cv2

        self.cv2 = cv2
        self.capture = cv2.VideoCapture(self.config.opencv_device, cv2.CAP_V4L2)
        if not self.capture.isOpened():
            raise RuntimeError(f"Could not open OpenCV camera device {self.config.opencv_device}")

        if self.config.opencv_fourcc:
            fourcc = cv2.VideoWriter_fourcc(*self.config.opencv_fourcc[:4])
            self.capture.set(cv2.CAP_PROP_FOURCC, fourcc)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self.capture.set(cv2.CAP_PROP_FPS, self.config.fps)
        LOGGER.info("Started OpenCV camera device %s", self.config.opencv_device)

    def capture_preview(self) -> Any | None:
        assert self.capture is not None
        ok, frame = self.capture.read()
        if not ok:
            return None
        height, width = frame.shape[:2]
        self.frame_size = (width, height)
        return frame

    def start_recording(self, output_path: Path) -> None:
        assert self.cv2 is not None
        width, height = self.frame_size or (self.config.width, self.config.height)
        fourcc = self.cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = self.cv2.VideoWriter(
            str(output_path),
            fourcc,
            float(self.config.fps),
            (width, height),
        )
        if not self.writer.isOpened():
            raise RuntimeError(f"Could not open video writer for {output_path}")

    def note_frame(self, frame: Any) -> None:
        if self.writer is not None:
            self.writer.write(frame)

    def stop_recording(self) -> None:
        if self.writer is not None:
            self.writer.release()
            self.writer = None

    def close(self) -> None:
        self.stop_recording()
        if self.capture is not None:
            self.capture.release()
            self.capture = None
