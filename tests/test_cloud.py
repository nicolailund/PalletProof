from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pallet_video_recorder.cloud import read_temperature_c


class CloudTest(unittest.TestCase):
    def test_reads_pi_temperature_millidegrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "temp"
            path.write_text("51234\n", encoding="utf-8")

            self.assertEqual(read_temperature_c(path), 51.2)

    def test_reads_temperature_degrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "temp"
            path.write_text("48.6\n", encoding="utf-8")

            self.assertEqual(read_temperature_c(path), 48.6)

    def test_missing_temperature_is_optional(self) -> None:
        self.assertIsNone(read_temperature_c(Path("/definitely/missing/palletproof/temp")))


if __name__ == "__main__":
    unittest.main()
