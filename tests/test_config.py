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

[camera]
preview_width = 1280
preview_height = 720
autofocus_mode = "continuous"

[motion]
roi = [0.1, 0.2, 0.3, 0.4]

[barcode]
roi = [0.2, 0.1, 0.5, 0.7]
rotation_degrees = [0, 90]
scan_scales = [1.0, 2.0]

[privacy]
fixed_masks = [[0.0, 0.0, 0.2, 0.2]]

[status_light]
backend = "act_led"
red_gpio_pin = 27
green_gpio_pin = 17
yellow_gpio_pin = 22
scan_flash_seconds = 0.2
sysfs_led_name = "ACT"
restore_trigger = "mmc0"
""",
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.camera.preview_width, 1280)
            self.assertEqual(config.camera.preview_height, 720)
            self.assertEqual(config.camera.autofocus_mode, "continuous")
            self.assertEqual(config.motion.roi, (0.1, 0.2, 0.3, 0.4))
            self.assertEqual(config.barcode.roi, (0.2, 0.1, 0.5, 0.7))
            self.assertEqual(config.barcode.rotation_degrees, (0, 90))
            self.assertEqual(config.barcode.scan_scales, (1.0, 2.0))
            self.assertEqual(config.privacy.fixed_masks, ((0.0, 0.0, 0.2, 0.2),))
            self.assertEqual(config.status_light.red_gpio_pin, 27)
            self.assertEqual(config.status_light.green_gpio_pin, 17)
            self.assertEqual(config.status_light.yellow_gpio_pin, 22)
            self.assertEqual(config.status_light.scan_flash_seconds, 0.2)
            self.assertEqual(config.status_light.backend, "act_led")
            self.assertEqual(config.status_light.sysfs_led_name, "ACT")
            self.assertEqual(config.status_light.restore_trigger, "mmc0")


if __name__ == "__main__":
    unittest.main()
