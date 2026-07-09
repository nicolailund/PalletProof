from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pallet_video_recorder.config import load_config


class ConfigTest(unittest.TestCase):
    def test_loads_example_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                """
[recording]
root_dir = "data"

[motion]
roi = [0.1, 0.2, 0.3, 0.4]

[privacy]
fixed_masks = [[0.0, 0.0, 0.2, 0.2]]
""",
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.motion.roi, (0.1, 0.2, 0.3, 0.4))
            self.assertEqual(config.privacy.fixed_masks, ((0.0, 0.0, 0.2, 0.2),))


if __name__ == "__main__":
    unittest.main()
