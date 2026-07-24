from __future__ import annotations

from datetime import datetime
import unittest
from pallet_video_recorder.scanner_schedule import ScannerSchedule


class ScannerScheduleTest(unittest.TestCase):
    def test_disabled_schedule_is_always_active(self) -> None:
        schedule = ScannerSchedule.from_cloud({"enabled": False, "active_start": "08:00", "active_end": "16:00", "active_days": []})

        self.assertTrue(schedule.is_active(datetime(2026, 7, 25, 3, 0)))

    def test_active_inside_same_day_window(self) -> None:
        schedule = ScannerSchedule.from_cloud(
            {
                "enabled": True,
                "active_start": "06:00",
                "active_end": "18:00",
                "active_days": [1, 2, 3, 4, 5],
                "timezone": "Europe/Copenhagen",
            }
        )

        self.assertTrue(schedule.is_active(datetime(2026, 7, 24, 9, 0)))
        self.assertFalse(schedule.is_active(datetime(2026, 7, 24, 21, 0)))
        self.assertFalse(schedule.is_active(datetime(2026, 7, 25, 9, 0)))

    def test_overnight_window_uses_previous_active_day_after_midnight(self) -> None:
        schedule = ScannerSchedule.from_cloud(
            {
                "enabled": True,
                "active_start": "22:00",
                "active_end": "06:00",
                "active_days": [1],
                "timezone": "Europe/Copenhagen",
            }
        )

        self.assertTrue(schedule.is_active(datetime(2026, 7, 27, 23, 0)))
        self.assertTrue(schedule.is_active(datetime(2026, 7, 28, 2, 0)))
        self.assertFalse(schedule.is_active(datetime(2026, 7, 28, 12, 0)))

    def test_invalid_cloud_payload_falls_back_to_always_active(self) -> None:
        schedule = ScannerSchedule.from_cloud({"enabled": True, "active_start": "bad", "active_end": "also-bad", "timezone": "Nope"})

        self.assertTrue(schedule.enabled)
        self.assertEqual(schedule.active_start.hour, 6)
        self.assertEqual(schedule.active_end.hour, 18)
        self.assertTrue(schedule.timezone)


if __name__ == "__main__":
    unittest.main()
