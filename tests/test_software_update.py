from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pallet_video_recorder.config import Paths, SoftwareUpdateConfig
from pallet_video_recorder.software_update import (
    SoftwareUpdateStateStore,
    SoftwareUpdateWorker,
    UpdateManifest,
    is_in_night_window,
    parse_update_manifest,
)


class SoftwareUpdateTest(unittest.TestCase):
    def test_parses_force_and_night_policy_aliases(self) -> None:
        force = parse_update_manifest(
            json.dumps(
                {
                    "schema_version": 1,
                    "update_id": "release-001",
                    "policy": "force_push",
                    "target_ref": "main",
                }
            )
        )
        night = parse_update_manifest(
            json.dumps(
                {
                    "schema_version": 1,
                    "update_id": "release-002",
                    "policy": "night-push",
                    "target_ref": "main",
                }
            )
        )

        self.assertEqual(force.policy, "force")
        self.assertEqual(night.policy, "night")

    def test_night_window_handles_same_day_and_midnight_windows(self) -> None:
        self.assertTrue(is_in_night_window(datetime(2026, 7, 23, 2, 30), 2, 4))
        self.assertFalse(is_in_night_window(datetime(2026, 7, 23, 5, 0), 2, 4))
        self.assertTrue(is_in_night_window(datetime(2026, 7, 23, 23, 30), 22, 3))
        self.assertTrue(is_in_night_window(datetime(2026, 7, 23, 1, 30), 22, 3))
        self.assertFalse(is_in_night_window(datetime(2026, 7, 23, 12, 0), 22, 3))

    def test_ready_to_apply_force_waits_for_idle_grace(self) -> None:
        worker = SoftwareUpdateWorker(
            SoftwareUpdateConfig(enabled=True, idle_grace_seconds=10.0),
            Paths.from_root(Path("data")),
        )
        worker.pending = UpdateManifest(update_id="release-001", policy="force")

        self.assertFalse(worker.ready_to_apply(9.9))
        self.assertTrue(worker.ready_to_apply(10.0))

    def test_ready_to_apply_night_waits_for_window(self) -> None:
        worker = SoftwareUpdateWorker(
            SoftwareUpdateConfig(
                enabled=True,
                idle_grace_seconds=0.0,
                night_start_hour=2,
                night_end_hour=4,
            ),
            Paths.from_root(Path("data")),
        )
        worker.pending = UpdateManifest(update_id="release-001", policy="night")

        self.assertFalse(worker.ready_to_apply(0.0, datetime(2026, 7, 23, 1, 59)))
        self.assertTrue(worker.ready_to_apply(0.0, datetime(2026, 7, 23, 2, 0)))

    def test_state_store_marks_update_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SoftwareUpdateStateStore(Path(temp_dir) / "state.json")
            manifest = UpdateManifest(
                update_id="release-001",
                policy="night",
                target_ref="main",
                target_commit="abc123",
                version="0.2.0",
            )

            store.mark_applied(manifest)
            state = store.load()

        self.assertEqual(state["applied_update_id"], "release-001")
        self.assertEqual(state["applied_policy"], "night")
        self.assertEqual(state["applied_target_commit"], "abc123")


if __name__ == "__main__":
    unittest.main()
