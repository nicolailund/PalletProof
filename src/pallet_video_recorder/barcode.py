from __future__ import annotations

import logging
import re
from typing import Any

from .config import BarcodeConfig

LOGGER = logging.getLogger(__name__)


class BarcodeReader:
    def __init__(self, config: BarcodeConfig) -> None:
        self.config = config
        self.accepted_pattern = re.compile(config.accepted_pattern)
        self._zxingcpp = self._optional_import("zxingcpp")
        self._pyzbar_decode = None
        if self._zxingcpp is None:
            try:
                from pyzbar.pyzbar import decode

                self._pyzbar_decode = decode
            except Exception as exc:  # pragma: no cover - depends on host libraries
                LOGGER.warning("No barcode backend loaded: %s", exc)

    def read(self, frame: Any) -> str | None:
        values = self._read_values(frame)
        for raw_value in values:
            value = self._normalize(raw_value)
            if value:
                return value
        return None

    def _read_values(self, frame: Any) -> list[str]:
        if self._zxingcpp is not None:
            try:
                results = self._zxingcpp.read_barcodes(frame)
                return [result.text for result in results if getattr(result, "text", None)]
            except Exception as exc:
                LOGGER.debug("zxing-cpp decode failed: %s", exc)

        if self._pyzbar_decode is not None:
            try:
                results = self._pyzbar_decode(frame)
                values: list[str] = []
                for result in results:
                    data = getattr(result, "data", b"")
                    if isinstance(data, bytes):
                        values.append(data.decode("utf-8", errors="replace"))
                    else:
                        values.append(str(data))
                return values
            except Exception as exc:
                LOGGER.debug("pyzbar decode failed: %s", exc)

        return []

    def _normalize(self, raw_value: str) -> str | None:
        value = raw_value.strip()
        if len(value) < self.config.min_chars or len(value) > self.config.max_chars:
            return None
        if not self.accepted_pattern.match(value):
            LOGGER.warning("Ignoring barcode outside accepted pattern: %r", value)
            return None
        return value

    @staticmethod
    def _optional_import(module_name: str) -> Any | None:
        try:
            return __import__(module_name)
        except Exception:
            return None
