from __future__ import annotations

import unittest

from pallet_video_recorder.barcode import BarcodeReader
from pallet_video_recorder.config import BarcodeConfig


class BarcodeReaderTest(unittest.TestCase):
    def test_requires_confirmed_repeated_read(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(confirm_read_count=2, duplicate_suppress_seconds=0.0)
        )
        reader._read_values = lambda frame: [" ORD-123 "]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))
        self.assertEqual(reader.read(object()), "ORD-123")

    def test_suppresses_recent_duplicate_scan(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(confirm_read_count=1, duplicate_suppress_seconds=60.0)
        )
        reader._read_values = lambda frame: ["ORD-123"]  # type: ignore[method-assign]

        self.assertEqual(reader.read(object()), "ORD-123")
        self.assertIsNone(reader.read(object()))

    def test_rejects_values_outside_accepted_pattern(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(confirm_read_count=1, accepted_pattern=r"^[0-9]+$")
        )
        reader._read_values = lambda frame: ["ABC-123"]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))

    def test_duplicate_values_in_same_frame_do_not_confirm(self) -> None:
        reader = BarcodeReader(
            BarcodeConfig(confirm_read_count=2, duplicate_suppress_seconds=0.0)
        )
        reader._read_values = lambda frame: ["ORD-123", "ORD-123"]  # type: ignore[method-assign]

        self.assertIsNone(reader.read(object()))


if __name__ == "__main__":
    unittest.main()
