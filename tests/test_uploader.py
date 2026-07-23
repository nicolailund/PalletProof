from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pallet_video_recorder.uploader import _guess_scanned_id, load_video_sidecar, sidecar_path


class UploaderTest(unittest.TestCase):
    def test_guesses_scanned_id_from_serial_prefixed_filename(self) -> None:
        self.assertEqual(
            _guess_scanned_id("PP-000123_REF-789_20260724_120000.mp4", "PP-000123"),
            "REF-789",
        )

    def test_loads_video_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "video.mp4"
            sidecar = sidecar_path(video)
            sidecar.write_text(json.dumps({"scanned_id": "REF-789"}), encoding="utf-8")

            self.assertEqual(load_video_sidecar(video)["scanned_id"], "REF-789")


if __name__ == "__main__":
    unittest.main()
