from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from .config import PrivacyConfig

LOGGER = logging.getLogger(__name__)


class PrivacyProcessor:
    def __init__(self, config: PrivacyConfig) -> None:
        self.config = config

    def process(self, source_path: Path, destination_path: Path) -> Path:
        if not self.config.enabled:
            shutil.move(str(source_path), str(destination_path))
            return destination_path

        if not self.config.face_blur and not self.config.fixed_masks:
            shutil.move(str(source_path), str(destination_path))
            return destination_path

        temp_path = destination_path.with_name(destination_path.name + ".privacy-part")
        if temp_path.exists():
            temp_path.unlink()

        try:
            self._blur_video(source_path, temp_path)
            temp_path.replace(destination_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        if self.config.delete_source_after_processing and source_path.exists():
            source_path.unlink()

        return destination_path

    def _blur_video(self, source_path: Path, destination_path: Path) -> None:
        import cv2

        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video for privacy processing: {source_path}")

        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(destination_path), fourcc, fps, (width, height))
        if not writer.isOpened():
            capture.release()
            raise RuntimeError(f"Could not open privacy output: {destination_path}")

        face_detector = self._face_detector(cv2) if self.config.face_blur else None

        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                self._apply_fixed_masks(frame, cv2)
                if face_detector is not None:
                    self._apply_face_blur(frame, cv2, face_detector)
                writer.write(frame)
        finally:
            capture.release()
            writer.release()

    def _face_detector(self, cv2: Any) -> Any:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(cascade_path)
        if detector.empty():
            raise RuntimeError("Could not load OpenCV face cascade")
        return detector

    def _apply_fixed_masks(self, frame: Any, cv2: Any) -> None:
        height, width = frame.shape[:2]
        for mask in self.config.fixed_masks:
            left, top, right, bottom = _rect_from_normalized(mask, width, height)
            region = frame[top:bottom, left:right]
            frame[top:bottom, left:right] = _blur_region(region, cv2)

    def _apply_face_blur(self, frame: Any, cv2: Any, detector: Any) -> None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
        for x, y, width, height in faces:
            padding_x = int(width * 0.25)
            padding_y = int(height * 0.35)
            left = max(0, x - padding_x)
            top = max(0, y - padding_y)
            right = min(frame.shape[1], x + width + padding_x)
            bottom = min(frame.shape[0], y + height + padding_y)
            region = frame[top:bottom, left:right]
            frame[top:bottom, left:right] = _blur_region(region, cv2)


def _rect_from_normalized(
    rect: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x, y, rect_width, rect_height = rect
    left = int(width * x)
    top = int(height * y)
    right = int(width * (x + rect_width))
    bottom = int(height * (y + rect_height))
    return left, top, right, bottom


def _blur_region(region: Any, cv2: Any) -> Any:
    if region.size == 0:
        return region
    kernel_width = max(23, (region.shape[1] // 8) | 1)
    kernel_height = max(23, (region.shape[0] // 8) | 1)
    return cv2.GaussianBlur(region, (kernel_width, kernel_height), 0)
