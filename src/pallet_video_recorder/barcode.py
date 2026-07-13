from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Iterable
import re
from typing import Any

from .config import BarcodeConfig

LOGGER = logging.getLogger(__name__)


class BarcodeReader:
    def __init__(self, config: BarcodeConfig) -> None:
        self.config = config
        self.accepted_pattern = re.compile(config.accepted_pattern)
        self._zxingcpp = self._optional_import("zxingcpp")
        self._cv2 = _optional_cv2()
        self._pyzbar_decode = None
        self._recent_reads: deque[tuple[str, float]] = deque()
        self._last_accepted_value: str | None = None
        self._last_accepted_at = 0.0
        if self._zxingcpp is None:
            try:
                from pyzbar.pyzbar import decode

                self._pyzbar_decode = decode
            except Exception as exc:  # pragma: no cover - depends on host libraries
                LOGGER.warning("No barcode backend loaded: %s", exc)

    def read(self, frame: Any) -> str | None:
        now = time.monotonic()
        seen_values: set[str] = set()
        for raw_value in self._read_values(frame):
            value = self._normalize(raw_value)
            if not value or value in seen_values:
                continue
            seen_values.add(value)
            accepted = self._confirm_read(value, now)
            if accepted is not None:
                return accepted
        return None

    def _read_values(self, frame: Any) -> Iterable[str]:
        for candidate in self._candidate_images(frame):
            yield from self._decode(candidate)

    def _decode(self, frame: Any) -> list[str]:
        if self._zxingcpp is not None:
            try:
                results = self._zxingcpp.read_barcodes(frame)
                return [result.text for result in results if getattr(result, "text", None)]
            except Exception as exc:
                LOGGER.debug("zxing-cpp decode failed: %s", exc)

        if self._pyzbar_decode is not None:
            try:
                results = self._pyzbar_decode(frame)
                values: list[str] = []
                for result in results:
                    data = getattr(result, "data", b"")
                    if isinstance(data, bytes):
                        values.append(data.decode("utf-8", errors="replace"))
                    else:
                        values.append(str(data))
                return values
            except Exception as exc:
                LOGGER.debug("pyzbar decode failed: %s", exc)

        return []

    def _candidate_images(self, frame: Any) -> Iterable[Any]:
        base = _crop_normalized(frame, self.config.roi)
        cv2 = self._cv2
        if cv2 is None or not hasattr(base, "shape"):
            yield base
            return

        for scale in self.config.scan_scales:
            scaled = _resize(base, scale, cv2)
            for degrees in self.config.rotation_degrees:
                rotated = _rotate(scaled, degrees, cv2)
                yield rotated
                if self.config.preprocess:
                    yield from _preprocessed(rotated, cv2)

    def _confirm_read(self, value: str, now: float) -> str | None:
        if self._is_duplicate(value, now):
            return None

        self._recent_reads.append((value, now))
        self._expire_recent_reads(now)

        count = sum(1 for recent_value, _ in self._recent_reads if recent_value == value)
        if count < self.config.confirm_read_count:
            return None

        self._last_accepted_value = value
        self._last_accepted_at = now
        self._recent_reads.clear()
        return value

    def _is_duplicate(self, value: str, now: float) -> bool:
        if self._last_accepted_value != value:
            return False
        elapsed = now - self._last_accepted_at
        return elapsed < self.config.duplicate_suppress_seconds

    def _expire_recent_reads(self, now: float) -> None:
        cutoff = now - self.config.confirm_window_seconds
        while self._recent_reads and self._recent_reads[0][1] < cutoff:
            self._recent_reads.popleft()

    def _normalize(self, raw_value: str) -> str | None:
        value = raw_value.strip()
        if len(value) < self.config.min_chars or len(value) > self.config.max_chars:
            return None
        if not self.accepted_pattern.match(value):
            LOGGER.warning("Ignoring barcode outside accepted pattern: %r", value)
            return None
        return value

    @staticmethod
    def _optional_import(module_name: str) -> Any | None:
        try:
            return __import__(module_name)
        except Exception:
            return None


def _optional_cv2() -> Any | None:
    try:
        import cv2

        return cv2
    except Exception:
        return None


def _crop_normalized(frame: Any, roi: tuple[float, float, float, float]) -> Any:
    if roi == (0.0, 0.0, 1.0, 1.0) or not hasattr(frame, "shape"):
        return frame

    height, width = frame.shape[:2]
    x, y, roi_width, roi_height = roi
    left = int(width * x)
    top = int(height * y)
    right = int(width * (x + roi_width))
    bottom = int(height * (y + roi_height))
    return frame[top:bottom, left:right]


def _resize(frame: Any, scale: float, cv2: Any) -> Any:
    if scale == 1.0:
        return frame
    height, width = frame.shape[:2]
    target_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(frame, target_size, interpolation=cv2.INTER_CUBIC)


def _rotate(frame: Any, degrees: int, cv2: Any) -> Any:
    normalized = degrees % 360
    if normalized == 0:
        return frame
    if normalized == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    height, width = frame.shape[:2]
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, normalized, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    target_width = int((height * sin) + (width * cos))
    target_height = int((height * cos) + (width * sin))
    matrix[0, 2] += (target_width / 2) - center[0]
    matrix[1, 2] += (target_height / 2) - center[1]
    return cv2.warpAffine(
        frame,
        matrix,
        (target_width, target_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _preprocessed(frame: Any, cv2: Any) -> Iterable[Any]:
    gray = _to_gray(frame, cv2)
    yield gray

    equalized = cv2.equalizeHist(gray)
    yield equalized

    thresholded = cv2.adaptiveThreshold(
        equalized,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    yield thresholded


def _to_gray(frame: Any, cv2: Any) -> Any:
    if len(frame.shape) == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
