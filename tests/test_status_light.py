from __future__ import annotations

import unittest

from pallet_video_recorder.config import StatusLightConfig
from pallet_video_recorder.status_light import StatusLight


class FakeLed:
    def __init__(self) -> None:
        self.is_on = False
        self.is_closed = False

    def on(self) -> None:
        self.is_on = True

    def off(self) -> None:
        self.is_on = False

    def close(self) -> None:
        self.is_closed = True


class FakeActLed:
    def __init__(self) -> None:
        self.flash_seconds: list[float] = []

    def flash(self, seconds: float) -> None:
        self.flash_seconds.append(seconds)


class StatusLightTest(unittest.TestCase):
    def test_maps_states_to_red_and_green_channels(self) -> None:
        light = StatusLight(StatusLightConfig(enabled=False, scan_flash_seconds=0.0))
        red = FakeLed()
        green = FakeLed()
        light.config = StatusLightConfig(enabled=True, scan_flash_seconds=0.0)
        light.red = red
        light.green = green

        light.idle()
        self.assertFalse(red.is_on)
        self.assertTrue(green.is_on)

        light.scanned()
        self.assertTrue(red.is_on)
        self.assertTrue(green.is_on)

        light.recording()
        self.assertTrue(red.is_on)
        self.assertFalse(green.is_on)

        light.close()
        self.assertFalse(red.is_on)
        self.assertFalse(green.is_on)
        self.assertTrue(red.is_closed)
        self.assertTrue(green.is_closed)

    def test_uses_dedicated_yellow_channel_when_configured(self) -> None:
        light = StatusLight(
            StatusLightConfig(enabled=False, yellow_gpio_pin=22, scan_flash_seconds=0.0)
        )
        red = FakeLed()
        green = FakeLed()
        yellow = FakeLed()
        light.config = StatusLightConfig(
            enabled=True,
            yellow_gpio_pin=22,
            scan_flash_seconds=0.0,
        )
        light.red = red
        light.green = green
        light.yellow = yellow

        light.scanned()

        self.assertFalse(red.is_on)
        self.assertFalse(green.is_on)
        self.assertTrue(yellow.is_on)

    def test_flashes_act_led_for_scanned_state(self) -> None:
        light = StatusLight(
            StatusLightConfig(
                enabled=False,
                backend="act_led",
                scan_flash_seconds=0.8,
            )
        )
        act_led = FakeActLed()
        light.config = StatusLightConfig(
            enabled=True,
            backend="act_led",
            scan_flash_seconds=0.8,
        )
        light.act_led = act_led

        light.idle()
        light.scanned()
        light.recording()

        self.assertEqual(act_led.flash_seconds, [0.8])


if __name__ == "__main__":
    unittest.main()
