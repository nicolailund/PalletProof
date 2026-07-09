from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .config import MotionConfig


@dataclass(frozen=True)
class MotionSample:
    score: float
    moving: bool
    still_for_seconds: float


class MotionDetector:
    def __init__(self, config: MotionConfig) -> None:
        self.config = config
        self.previous_gray: Any | None = None
        self.last_moving_at: float | None = None

    def reset(self) -> None:
        self.previous_gray = None
        self.last_moving_at = None

    def update(self, frame: Any) -> MotionSample:
        import cv2

        now = time.monotonic()
        gray = self._prepare_gray(frame, cv2)

        if self.previous_gray is None:
            self.previous_gray = gray
            return MotionSample(score=0.0, moving=False, still_for_seconds=0.0)

        diff = cv2.absdiff(gray, self.previous_gray)
        self.previous_gray = gray
        score = float(diff.mean()) / 255.0
        moving = score >= self.config.threshold

        if moving:
            self.last_moving_at = now
            still_for = 0.0
        elif self.last_moving_at is None:
            still_for = 0.0
        else:
            still_for = now - self.last_moving_at

        return MotionSample(score=score, moving=moving, still_for_seconds=still_for)

    def _prepare_gray(self, frame: Any, cv2: Any) -> Any:
        cropped = crop_normalized(frame, self.config.roi)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY) if len(cropped.shape) == 3 else cropped
        gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(gray, (5, 5), 0)


def crop_normalized(frame: Any, roi: tuple[float, float, float, float]) -> Any:
    height, width = frame.shape[:2]
    x, y, roi_width, roi_height = roi
    left = int(width * x)
    top = int(height * y)
    right = int(width * (x + roi_width))
    bottom = int(height * (y + roi_height))
    return frame[top:bottom, left:right]
