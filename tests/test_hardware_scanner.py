from __future__ import annotations

import threading
import time
import unittest

from pallet_video_recorder.config import HardwareScannerConfig
from pallet_video_recorder.hardware_scanner import (
    HardwareScannerWorker,
    ScannerDevice,
    _device_sort_key,
    _hid_key_to_char,
)


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

    def test_discards_pending_results(self) -> None:
        worker = HardwareScannerWorker(HardwareScannerConfig(validate_gs1_ai01_check_digit=False))
        worker.accept_for_test("ORD-123")
        worker.accept_for_test("ORD-456")

        self.assertEqual(worker.discard_pending_results(), 2)
        self.assertIsNone(worker.poll())
        self.assertEqual(worker.discard_pending_results(), 0)

    def test_treats_buffer_as_complete_after_idle_timeout(self) -> None:
        now = [100.0]
        worker = HardwareScannerWorker(
            HardwareScannerConfig(line_idle_seconds=0.25),
            clock=lambda: now[0],
        )
        buffer = bytearray(b"ORD-123")

        self.assertFalse(worker._is_idle_line_complete(bool(buffer), last_byte_at=100.0))
        now[0] = 100.3

        self.assertTrue(worker._is_idle_line_complete(bool(buffer), last_byte_at=100.0))

    def test_maps_hid_keyboard_events_to_characters(self) -> None:
        self.assertEqual(_hid_key_to_char(30, shifted=False), "a")
        self.assertEqual(_hid_key_to_char(30, shifted=True), "A")
        self.assertEqual(_hid_key_to_char(10, shifted=True), "(")
        self.assertEqual(_hid_key_to_char(11, shifted=True), ")")
        self.assertEqual(_hid_key_to_char(12, shifted=False), "-")
        self.assertEqual(_hid_key_to_char(13, shifted=True), "+")

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

    def test_prefers_hid_scanner_in_auto_mode(self) -> None:
        devices = [
            ScannerDevice("serial", "/dev/serial/by-id/usb-Quectel_4G_Modem-if00-port0"),
            ScannerDevice("hid_keyboard", "/dev/input/by-id/usb-SAGE_Technology_QR_Scanner-event-kbd"),
        ]

        self.assertEqual(
            sorted(devices, key=_device_sort_key)[0],
            ScannerDevice("hid_keyboard", "/dev/input/by-id/usb-SAGE_Technology_QR_Scanner-event-kbd"),
        )

    def test_disable_triggering_turns_output_off_during_active_pulse(self) -> None:
        output = FakeTriggerOutput()
        worker = HardwareScannerWorker(
            HardwareScannerConfig(
                trigger_gpio_enabled=True,
                trigger_pulse_seconds=10.0,
            )
        )
        worker._trigger_output = output
        worker._trigger_event.set()

        thread = threading.Thread(target=worker._pulse_trigger)
        thread.start()
        time.sleep(0.05)
        worker.disable_triggering()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(output.active, False)
        self.assertIn("on", output.calls)
        self.assertEqual(output.calls[-1], "off")


class FakeTriggerOutput:
    def __init__(self) -> None:
        self.active = False
        self.calls: list[str] = []

    def on(self) -> None:
        self.active = True
        self.calls.append("on")

    def off(self) -> None:
        self.active = False
        self.calls.append("off")


if __name__ == "__main__":
    unittest.main()
