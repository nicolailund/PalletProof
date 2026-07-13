from __future__ import annotations

import unittest

from pallet_video_recorder.barcode import BarcodeReader
from pallet_video_recorder.barcode import _rotate
from pallet_video_recorder.config import BarcodeConfig

np = None
cv2 = None
try:
    import cv2
    import numpy as np
except Exception:
    pass


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class BarcodeReaderTest(unittest.TestCase):
    def test_requires_confirmed_repeated_read(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=2,
                duplicate_suppress_seconds=0.0,
                ambient_suppress_seconds=0.0,
            )
        )
        reader._read_values = lambda frame: [" ORD-123 "]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))
        self.assertEqual(reader.read(object()), "ORD-123")

    def test_accepts_gs1_style_parenthesized_values(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=1,
                duplicate_suppress_seconds=0.0,
                ambient_suppress_seconds=0.0,
            )
        )
        reader._read_values = lambda frame: ["(01)08584012360472"]  # type: ignore[method-assign]

        self.assertEqual(reader.read(object()), "(01)08584012360472")

    def test_rejects_invalid_gs1_ai01_check_digit(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=1,
                duplicate_suppress_seconds=0.0,
                ambient_suppress_seconds=0.0,
            )
        )
        reader._read_values = lambda frame: ["(01)08584012360471"]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))

    def test_suppresses_recent_duplicate_scan(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=1,
                duplicate_suppress_seconds=60.0,
                ambient_suppress_seconds=0.0,
            )
        )
        reader._read_values = lambda frame: ["ORD-123"]  # type: ignore[method-assign]

        self.assertEqual(reader.read(object()), "ORD-123")
        self.assertIsNone(reader.read(object()))

    def test_rejects_values_outside_accepted_pattern(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=1,
                accepted_pattern=r"^[0-9]+$",
                ambient_suppress_seconds=0.0,
            )
        )
        reader._read_values = lambda frame: ["ABC-123"]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))

    def test_duplicate_values_in_same_frame_do_not_confirm(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=2,
                duplicate_suppress_seconds=0.0,
                ambient_suppress_seconds=0.0,
            )
        )
        reader._read_values = lambda frame: ["ORD-123", "ORD-123"]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))

    def test_suppresses_codes_visible_during_ambient_window(self) -> None:
        clock = FakeClock()
        reader = BarcodeReader(
            BarcodeConfig(
                confirm_read_count=1,
                duplicate_suppress_seconds=0.0,
                ambient_suppress_seconds=2.0,
                ambient_absent_seconds=1.0,
            ),
            clock=clock,
        )
        reader._read_values = lambda frame: ["ORD-123"]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))
        clock.advance(0.9)
        self.assertIsNone(reader.read(object()))
        clock.advance(0.9)
        self.assertIsNone(reader.read(object()))
        clock.advance(0.4)
        self.assertIsNone(reader.read(object()))
        clock.advance(1.1)
        self.assertEqual(reader.read(object()), "ORD-123")

    @unittest.skipIf(np is None or cv2 is None, "numpy/opencv are not installed")
    def test_arbitrary_rotation_expands_canvas(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)

        rotated = _rotate(frame, 45, cv2)

        self.assertGreater(rotated.shape[0], frame.shape[0])
        self.assertGreater(rotated.shape[1], frame.shape[1])


if __name__ == "__main__":
    unittest.main()
