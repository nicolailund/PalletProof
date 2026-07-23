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
autofocus_range = "full"
autofocus_speed = "fast"

[motion]
roi = [0.1, 0.2, 0.3, 0.4]

[barcode]
enabled = true
roi = [0.2, 0.1, 0.5, 0.7]
rotation_degrees = [0, 90]
formats = ["Code128", "Code39"]
scan_scales = [1.0, 2.0]

[hardware_scanner]
enabled = true
mode = "hid_keyboard"
device = "/dev/serial/by-id/usb-test-scanner"
baudrate = 9600
reconnect_seconds = 3.0
line_idle_seconds = 0.4
trigger_gpio_enabled = true
trigger_gpio_pin = 23
trigger_interval_seconds = 2.0
trigger_pulse_seconds = 0.15
trigger_active_high = false
duplicate_suppress_seconds = 1.0
min_chars = 5
max_chars = 80
accepted_pattern = "^[A-Z0-9-]+$"
validate_gs1_ai01_check_digit = false

[device]
provisioning_required = true
identity_file = "identity/device.json"
serial_number = "PP-DEV-001"
provisioning_qr_prefix = "PALLETPROOF"

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

[preview]
enabled = true
host = "0.0.0.0"
port = 8080
max_fps = 5.0
width = 960
jpeg_quality = 70

[software_update]
enabled = true
manifest_url = "https://raw.githubusercontent.com/nicolailund/PalletProof/main/updates/palletproof-update.json"
repository_dir = "/home/palletcam/pallet-video"
state_file = "updates/state.json"
install_command = "bash scripts/install_from_github.sh"
check_interval_seconds = 60.0
request_timeout_seconds = 5.0
install_timeout_seconds = 300.0
idle_grace_seconds = 20.0
apply_retry_seconds = 120.0
night_start_hour = 1
night_end_hour = 5
""",
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.camera.preview_width, 1280)
            self.assertEqual(config.camera.preview_height, 720)
            self.assertEqual(config.camera.autofocus_mode, "continuous")
            self.assertEqual(config.camera.autofocus_range, "full")
            self.assertEqual(config.camera.autofocus_speed, "fast")
            self.assertTrue(config.barcode.enabled)
            self.assertEqual(config.barcode.scan_every_n_frames, 2)
            self.assertEqual(config.barcode.confirm_read_count, 2)
            self.assertTrue(config.barcode.validate_gs1_ai01_check_digit)
            self.assertTrue(config.hardware_scanner.enabled)
            self.assertEqual(config.hardware_scanner.mode, "hid_keyboard")
            self.assertEqual(config.hardware_scanner.device, "/dev/serial/by-id/usb-test-scanner")
            self.assertEqual(config.hardware_scanner.baudrate, 9600)
            self.assertEqual(config.hardware_scanner.reconnect_seconds, 3.0)
            self.assertEqual(config.hardware_scanner.line_idle_seconds, 0.4)
            self.assertTrue(config.hardware_scanner.trigger_gpio_enabled)
            self.assertEqual(config.hardware_scanner.trigger_gpio_pin, 23)
            self.assertEqual(config.hardware_scanner.trigger_interval_seconds, 2.0)
            self.assertEqual(config.hardware_scanner.trigger_pulse_seconds, 0.15)
            self.assertFalse(config.hardware_scanner.trigger_active_high)
            self.assertEqual(config.hardware_scanner.duplicate_suppress_seconds, 1.0)
            self.assertEqual(config.hardware_scanner.min_chars, 5)
            self.assertEqual(config.hardware_scanner.max_chars, 80)
            self.assertEqual(config.hardware_scanner.accepted_pattern, "^[A-Z0-9-]+$")
            self.assertFalse(config.hardware_scanner.validate_gs1_ai01_check_digit)
            self.assertTrue(config.device.provisioning_required)
            self.assertEqual(config.device.identity_file, Path("identity/device.json"))
            self.assertEqual(config.device.serial_number, "PP-DEV-001")
            self.assertEqual(config.device.provisioning_qr_prefix, "PALLETPROOF")
            self.assertEqual(config.motion.roi, (0.1, 0.2, 0.3, 0.4))
            self.assertEqual(config.motion.minimum_recording_seconds, 30.0)
            self.assertEqual(config.barcode.roi, (0.2, 0.1, 0.5, 0.7))
            self.assertEqual(config.barcode.rotation_degrees, (0, 90))
            self.assertEqual(config.barcode.formats, ("Code128", "Code39"))
            self.assertEqual(config.barcode.scan_scales, (1.0, 2.0))
            self.assertEqual(config.privacy.fixed_masks, ((0.0, 0.0, 0.2, 0.2),))
            self.assertEqual(config.status_light.red_gpio_pin, 27)
            self.assertEqual(config.status_light.green_gpio_pin, 17)
            self.assertEqual(config.status_light.yellow_gpio_pin, 22)
            self.assertEqual(config.status_light.scan_flash_seconds, 0.2)
            self.assertEqual(config.status_light.backend, "act_led")
            self.assertEqual(config.status_light.sysfs_led_name, "ACT")
            self.assertEqual(config.status_light.restore_trigger, "mmc0")
            self.assertTrue(config.preview.enabled)
            self.assertEqual(config.preview.host, "0.0.0.0")
            self.assertEqual(config.preview.port, 8080)
            self.assertEqual(config.preview.max_fps, 5.0)
            self.assertEqual(config.preview.width, 960)
            self.assertEqual(config.preview.jpeg_quality, 70)
            self.assertTrue(config.software_update.enabled)
            self.assertEqual(
                config.software_update.manifest_url,
                "https://raw.githubusercontent.com/nicolailund/PalletProof/main/updates/palletproof-update.json",
            )
            self.assertEqual(config.software_update.repository_dir, Path("/home/palletcam/pallet-video"))
            self.assertEqual(config.software_update.state_file, Path("updates/state.json"))
            self.assertEqual(config.software_update.install_command, "bash scripts/install_from_github.sh")
            self.assertEqual(config.software_update.check_interval_seconds, 60.0)
            self.assertEqual(config.software_update.request_timeout_seconds, 5.0)
            self.assertEqual(config.software_update.install_timeout_seconds, 300.0)
            self.assertEqual(config.software_update.idle_grace_seconds, 20.0)
            self.assertEqual(config.software_update.apply_retry_seconds, 120.0)
            self.assertEqual(config.software_update.night_start_hour, 1)
            self.assertEqual(config.software_update.night_end_hour, 5)


if __name__ == "__main__":
    unittest.main()
