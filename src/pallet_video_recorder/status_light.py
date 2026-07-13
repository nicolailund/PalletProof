from __future__ import annotations

import logging
from pathlib import Path
import re
import subprocess
import time
from typing import Literal

from .config import StatusLightConfig

LOGGER = logging.getLogger(__name__)

LightState = Literal["off", "idle", "scanned", "recording"]


class StatusLight:
    def __init__(self, config: StatusLightConfig) -> None:
        self.config = config
        self.red = None
        self.green = None
        self.yellow = None
        self.act_led = None
        if not config.enabled:
            return

        if config.backend == "act_led":
            self.act_led = SysfsLedFlasher(config.sysfs_led_name, config.restore_trigger)
            return

        try:
            from gpiozero import LED

            self.red = LED(config.red_gpio_pin, active_high=config.active_high)
            self.green = LED(config.green_gpio_pin, active_high=config.active_high)
            if config.yellow_gpio_pin is not None:
                self.yellow = LED(config.yellow_gpio_pin, active_high=config.active_high)
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            LOGGER.warning("GPIO status light unavailable; status changes will only be logged: %s", exc)

    def idle(self) -> None:
        self._set("idle")

    def scanned(self) -> None:
        self._set("scanned")
        if self.config.scan_flash_seconds > 0:
            time.sleep(self.config.scan_flash_seconds)

    def recording(self) -> None:
        self._set("recording")

    def off(self) -> None:
        self._set("off")

    def close(self) -> None:
        if self.act_led is None:
            self.off()
        for led in (self.red, self.green, self.yellow):
            if led is not None:
                led.close()
        self.red = None
        self.green = None
        self.yellow = None
        self.act_led = None

    def _set(self, state: LightState) -> None:
        if not self.config.enabled:
            return
        if self.act_led is not None:
            LOGGER.info("STATUS_LIGHT %s", state.upper())
            if state == "scanned":
                self.act_led.flash(self.config.scan_flash_seconds)
            return

        dedicated_yellow = self.yellow is not None
        red_on = state == "recording" or (state == "scanned" and not dedicated_yellow)
        green_on = state == "idle" or (state == "scanned" and not dedicated_yellow)
        yellow_on = state == "scanned"

        if self.red is None or self.green is None:
            LOGGER.info("STATUS_LIGHT %s", state.upper())
            return

        self.red.on() if red_on else self.red.off()
        self.green.on() if green_on else self.green.off()
        if self.yellow is not None:
            self.yellow.on() if yellow_on else self.yellow.off()


class SysfsLedFlasher:
    def __init__(self, led_name: str, restore_trigger: str) -> None:
        self.led_dir = Path("/sys/class/leds") / led_name
        self.restore_trigger = restore_trigger

    def flash(self, seconds: float) -> None:
        if seconds <= 0:
            return
        trigger_path = self.led_dir / "trigger"
        brightness_path = self.led_dir / "brightness"
        if not trigger_path.exists() or not brightness_path.exists():
            LOGGER.warning("ACT LED feedback unavailable; %s does not exist", self.led_dir)
            return

        original_trigger = self._current_trigger(trigger_path) or self.restore_trigger
        try:
            self._write(trigger_path, "none")
            self._blink(brightness_path, seconds)
        except Exception as exc:  # pragma: no cover - depends on Pi sysfs/sudo
            LOGGER.warning("ACT LED feedback unavailable: %s", exc)
        finally:
            try:
                self._write(trigger_path, original_trigger)
            except Exception as exc:  # pragma: no cover - depends on Pi sysfs/sudo
                LOGGER.warning("Could not restore ACT LED trigger to %s: %s", original_trigger, exc)

    def _blink(self, brightness_path: Path, seconds: float) -> None:
        total_seconds = max(0.2, seconds)
        blink_count = max(1, min(6, round(total_seconds / 0.25)))
        half_period = max(0.07, total_seconds / (blink_count * 2))
        for _ in range(blink_count):
            self._write(brightness_path, "1")
            time.sleep(half_period)
            self._write(brightness_path, "0")
            time.sleep(half_period)

    def _current_trigger(self, trigger_path: Path) -> str | None:
        text = trigger_path.read_text(encoding="utf-8")
        match = re.search(r"\[([^\]]+)\]", text)
        if match is None:
            return None
        return match.group(1)

    def _write(self, path: Path, value: str) -> None:
        content = f"{value}\n"
        try:
            path.write_text(content, encoding="utf-8")
            return
        except OSError:
            pass

        subprocess.run(
            ["sudo", "-n", "tee", str(path)],
            input=content,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=2,
        )
