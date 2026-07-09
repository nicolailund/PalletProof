from __future__ import annotations

import logging
import time

from .config import SoundConfig

LOGGER = logging.getLogger(__name__)


class Beeper:
    def __init__(self, config: SoundConfig) -> None:
        self.config = config
        self.buzzer = None
        if not config.enabled:
            return

        try:
            from gpiozero import Buzzer

            self.buzzer = Buzzer(config.gpio_pin)
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            LOGGER.warning("GPIO buzzer unavailable; barcode beep will only be logged: %s", exc)

    def beep(self) -> None:
        if not self.config.enabled:
            return
        if self.buzzer is None:
            LOGGER.info("BEEP")
            return
        self.buzzer.on()
        time.sleep(self.config.duration_seconds)
        self.buzzer.off()

    def close(self) -> None:
        if self.buzzer is not None:
            self.buzzer.close()
            self.buzzer = None
