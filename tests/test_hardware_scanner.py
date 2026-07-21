from __future__ import annotations

import unittest

from pallet_video_recorder.config import HardwareScannerConfig
from pallet_video_recorder.hardware_scanner import HardwareScannerWorker, _device_sort_key


class HardwareScannerWorkerTest(unittest.TestCase):
    def test_accepts_normalized_scanner_line(self) -> None:
        worker = HardwareScannerWorker(HardwareScannerConfig())

        worker.accept_for_test("  ORD-123\r\n")

        self.assertEqual(worker.poll(), "ORD-123")
        self.assertIsNone(worker.poll())
        self.assertEqual(worker.stats().read_count, 1)

    def test_rejects_values_outside_pattern(self) -> None:
        worker = HardwareScannerWorker(
            HardwareScannerConfig(
                accepted_pattern=r"^[A-Z0-9-]+$",
                min_chars=1,
            )
        )

        worker.accept_for_test("order 123")

        self.assertIsNone(worker.poll())
        self.assertEqual(worker.stats().read_count, 0)

    def test_suppresses_immediate_duplicate_reads(self) -> None:
        now = [100.0]
        worker = HardwareScannerWorker(
            HardwareScannerConfig(duplicate_suppress_seconds=2.0),
            clock=lambda: now[0],
        )

        worker.accept_for_test("ORD-123")
        worker.accept_for_test("ORD-123")
        now[0] += 2.1
        worker.accept_for_test("ORD-123")

        self.assertEqual(worker.poll(), "ORD-123")
        self.assertEqual(worker.poll(), "ORD-123")
        self.assertIsNone(worker.poll())
        self.assertEqual(worker.stats().read_count, 2)

    def test_rejects_invalid_gs1_ai01_check_digit(self) -> None:
        worker = HardwareScannerWorker(HardwareScannerConfig())

        worker.accept_for_test("(01)08584012360473")

        self.assertIsNone(worker.poll())

    def test_treats_buffer_as_complete_after_idle_timeout(self) -> None:
        now = [100.0]
        worker = HardwareScannerWorker(
            HardwareScannerConfig(line_idle_seconds=0.25),
            clock=lambda: now[0],
        )
        buffer = bytearray(b"ORD-123")

        self.assertFalse(worker._is_idle_line_complete(buffer, last_byte_at=100.0))
        now[0] = 100.3

        self.assertTrue(worker._is_idle_line_complete(buffer, last_byte_at=100.0))

    def test_prefers_scanner_like_device_over_modem(self) -> None:
        paths = [
            "/dev/serial/by-id/usb-Quectel_4G_Modem-if00-port0",
            "/dev/ttyACM0",
            "/dev/serial/by-id/usb-SparkFun_Barcode_Scanner-if00",
        ]

        self.assertEqual(
            sorted(paths, key=_device_sort_key)[0],
            "/dev/serial/by-id/usb-SparkFun_Barcode_Scanner-if00",
        )


if __name__ == "__main__":
    unittest.main()
