from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any

from .barcode import BarcodeReader
from .config import BarcodeConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BarcodeScanStats:
    submitted_count: int
    completed_count: int
    latest_sequence: int
    scanned_sequence: int
    busy: bool
    current_elapsed_seconds: float | None
    last_duration_seconds: float | None
    last_result: str | None
    queued_results: int


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
        self._submitted_count = 0
        self._completed_count = 0
        self._scan_started_at: float | None = None
        self._last_duration_seconds: float | None = None
        self._last_result: str | None = None

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
            self._submitted_count += 1
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

    def stats(self) -> BarcodeScanStats:
        now = time.monotonic()
        with self._condition:
            current_elapsed = (
                None if self._scan_started_at is None else now - self._scan_started_at
            )
            return BarcodeScanStats(
                submitted_count=self._submitted_count,
                completed_count=self._completed_count,
                latest_sequence=self._latest_sequence,
                scanned_sequence=self._scanned_sequence,
                busy=self._scan_started_at is not None,
                current_elapsed_seconds=current_elapsed,
                last_duration_seconds=self._last_duration_seconds,
                last_result=self._last_result,
                queued_results=len(self._results),
            )

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

            started_at = time.monotonic()
            with self._condition:
                self._scan_started_at = started_at

            try:
                with self._reader_lock:
                    value = self.reader.read(frame)
            except Exception:
                LOGGER.exception("Barcode scan failed")
                value = None
            duration = time.monotonic() - started_at

            with self._condition:
                self._scanned_sequence = max(self._scanned_sequence, sequence)
                self._completed_count += 1
                self._scan_started_at = None
                self._last_duration_seconds = duration
                self._last_result = value
                if value is not None:
                    self._results.append(value)
