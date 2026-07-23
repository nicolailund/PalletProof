from __future__ import annotations

import unittest

from pallet_video_recorder.log_safety import safe_scan_value


class LogSafetyTest(unittest.TestCase):
    def test_keeps_short_order_number_visible(self) -> None:
        self.assertEqual(safe_scan_value("ORD-12345"), "ORD-12345")

    def test_redacts_palletproof_qr(self) -> None:
        redacted = safe_scan_value("PALLETPROOF1." + ("a" * 160))

        self.assertNotIn("a" * 20, redacted)
        self.assertIn("redacted", redacted)
        self.assertIn("len=173", redacted)

    def test_redacts_long_unknown_scan(self) -> None:
        redacted = safe_scan_value("X" * 120)

        self.assertNotIn("X" * 20, redacted)
        self.assertIn("len=120", redacted)


if __name__ == "__main__":
    unittest.main()
