from __future__ import annotations

import unittest
from datetime import datetime

from pallet_video_recorder.filenames import (
    build_video_name,
    sanitize_order_number,
    sanitize_scanned_id,
    sanitize_serial_number,
)


class FilenameTest(unittest.TestCase):
    def test_sanitize_order_number(self) -> None:
        self.assertEqual(sanitize_order_number(" ORD/123  "), "ORD_123")
        self.assertEqual(sanitize_order_number("(01)08584012360472"), "01_08584012360472")

    def test_sanitize_scanned_id(self) -> None:
        self.assertEqual(sanitize_scanned_id(" REF/ABC  "), "REF_ABC")

    def test_sanitize_serial_number(self) -> None:
        self.assertEqual(sanitize_serial_number(" PP/000123  "), "PP_000123")

    def test_build_video_name(self) -> None:
        name = build_video_name("ORD-123", ".mp4", datetime(2026, 7, 5, 15, 30, 12))
        self.assertEqual(name, "ORD-123_20260705_153012.mp4")

    def test_build_video_name_with_serial_number(self) -> None:
        name = build_video_name(
            "ORD-123",
            ".mp4",
            datetime(2026, 7, 5, 15, 30, 12),
            serial_number="PP-000123",
        )
        self.assertEqual(name, "PP-000123_ORD-123_20260705_153012.mp4")


if __name__ == "__main__":
    unittest.main()
