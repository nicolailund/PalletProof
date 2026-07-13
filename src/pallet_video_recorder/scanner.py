from __future__ import annotations

from collections import deque
import logging
import threading
from typing import Any

from .barcode import BarcodeReader
from .config import BarcodeConfig

LOGGER = logging.getLogger(__name__)


class BarcodeScanWorker:
    def __init__(self, config: BarcodeConfig) -> None:
        self.reader = BarcodeReader(config)
        self._condition = threading.Condition()
        self._reader_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._latest_frame: Any | None = None
        self._latest_sequence = 0
        self._scanned_sequence = 0
        self._results: deque[str] = deque()

    def start(self) -> None:
        with self._condition:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                name="barcode-scan",
                daemon=True,
            )
            self._thread.start()

    def submit(self, frame: Any) -> None:
        with self._condition:
            if not self._running:
                return
            self._latest_sequence += 1
            self._latest_frame = frame
            self._condition.notify()

    def poll(self) -> str | None:
        with self._condition:
            if not self._results:
                return None
            return self._results.popleft()

    def start_ambient_suppression(self) -> None:
        with self._reader_lock:
            self.reader.start_ambient_suppression()

    def stop(self) -> None:
        with self._condition:
            if not self._running:
                return
            self._running = False
            self._condition.notify_all()

        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: not self._running or self._latest_sequence > self._scanned_sequence
                )
                if not self._running:
                    return
                frame = self._latest_frame
                sequence = self._latest_sequence

            if frame is None:
                with self._condition:
                    self._scanned_sequence = max(self._scanned_sequence, sequence)
                continue

            try:
                with self._reader_lock:
                    value = self.reader.read(frame)
            except Exception:
                LOGGER.exception("Barcode scan failed")
                value = None

            with self._condition:
                self._scanned_sequence = max(self._scanned_sequence, sequence)
                if value is not None:
                    self._results.append(value)
