from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import glob
import logging
import re
import select
import threading
import time
from typing import BinaryIO

from .barcode import _has_valid_gs1_ai01
from .config import HardwareScannerConfig

LOGGER = logging.getLogger(__name__)

AUTO_DEVICE_PATTERNS = (
    "/dev/serial/by-id/*",
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
)

SCANNER_DEVICE_HINTS = (
    "barcode",
    "scanner",
    "de2120",
    "sparkfun",
    "symbol",
    "honeywell",
    "zebra",
)

MODEM_DEVICE_HINTS = (
    "modem",
    "wwan",
    "lte",
    "5g",
    "4g",
    "gsm",
    "huawei",
    "quectel",
    "sierra",
    "simcom",
)


@dataclass(frozen=True)
class HardwareScannerStats:
    enabled: bool
    connected: bool
    device: str | None
    read_count: int
    queued_results: int
    last_result: str | None


class HardwareScannerWorker:
    def __init__(
        self,
        config: HardwareScannerConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._clock = clock
        self.accepted_pattern = re.compile(config.accepted_pattern)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._results: deque[str] = deque()
        self._connected = False
        self._device: str | None = None
        self._read_count = 0
        self._last_result: str | None = None
        self._last_accepted_value: str | None = None
        self._last_accepted_at = 0.0

    def start(self) -> None:
        if not self.config.enabled:
            LOGGER.info("Hardware barcode scanner disabled")
            return

        if self._thread is not None:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hardware-barcode-scanner",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def poll(self) -> str | None:
        with self._lock:
            if not self._results:
                return None
            return self._results.popleft()

    def stats(self) -> HardwareScannerStats:
        with self._lock:
            return HardwareScannerStats(
                enabled=self.config.enabled,
                connected=self._connected,
                device=self._device,
                read_count=self._read_count,
                queued_results=len(self._results),
                last_result=self._last_result,
            )

    def normalize(self, raw_value: str) -> str | None:
        value = raw_value.replace("\x00", "").strip()
        value = "".join(character for character in value if character.isprintable())
        if len(value) < self.config.min_chars or len(value) > self.config.max_chars:
            return None
        if self.accepted_pattern.fullmatch(value) is None:
            LOGGER.warning("Ignoring hardware barcode outside accepted pattern: %r", value)
            return None
        if self.config.validate_gs1_ai01_check_digit and not _has_valid_gs1_ai01(value):
            LOGGER.warning("Ignoring GS1 AI(01) barcode with invalid check digit: %r", value)
            return None
        return value

    def accept_for_test(self, raw_value: str) -> None:
        value = self.normalize(raw_value)
        if value is not None:
            self._queue_value(value)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            device = self._resolve_device()
            if device is None:
                self._set_connected(False, None)
                LOGGER.warning(
                    "No hardware barcode scanner serial device found; retrying in %.1fs",
                    self.config.reconnect_seconds,
                )
                self._stop_event.wait(self.config.reconnect_seconds)
                continue

            try:
                self._read_device(device)
            except Exception as exc:
                if not self._stop_event.is_set():
                    LOGGER.warning("Hardware barcode scanner disconnected or failed on %s: %s", device, exc)
            finally:
                self._set_connected(False, device)

            self._stop_event.wait(self.config.reconnect_seconds)

    def _read_device(self, device: str) -> None:
        LOGGER.info("Opening hardware barcode scanner on %s at %s baud", device, self.config.baudrate)
        with open(device, "rb", buffering=0) as handle:
            _configure_serial(handle.fileno(), self.config.baudrate)
            self._set_connected(True, device)
            LOGGER.info("Hardware barcode scanner ready on %s", device)
            self._read_loop(handle)

    def _read_loop(self, handle: BinaryIO) -> None:
        buffer = bytearray()
        max_buffer_size = max(self.config.max_chars * 4, 256)
        last_byte_at: float | None = None

        while not self._stop_event.is_set():
            timeout = _read_timeout(self.config.line_idle_seconds)
            ready, _, _ = select.select([handle], [], [], timeout)
            if not ready:
                if self._is_idle_line_complete(buffer, last_byte_at):
                    self._handle_line(buffer)
                    buffer.clear()
                    last_byte_at = None
                continue

            chunk = handle.read(64)
            if not chunk:
                raise OSError("serial device returned EOF")

            for byte in chunk:
                if byte in (10, 13):
                    self._handle_line(buffer)
                    buffer.clear()
                    last_byte_at = None
                    continue

                if byte == 0:
                    continue

                buffer.append(byte)
                last_byte_at = self._clock()
                if len(buffer) > max_buffer_size:
                    LOGGER.warning("Ignoring overlong hardware barcode scanner line")
                    buffer.clear()
                    last_byte_at = None

    def _handle_line(self, buffer: bytearray) -> None:
        if not buffer:
            return
        raw_value = bytes(buffer).decode("utf-8", errors="replace")
        value = self.normalize(raw_value)
        if value is not None:
            self._queue_value(value)

    def _is_idle_line_complete(self, buffer: bytearray, last_byte_at: float | None) -> bool:
        if not buffer or last_byte_at is None or self.config.line_idle_seconds <= 0:
            return False
        return self._clock() - last_byte_at >= self.config.line_idle_seconds

    def _queue_value(self, value: str) -> None:
        now = self._clock()
        with self._lock:
            if self._last_accepted_value == value:
                elapsed = now - self._last_accepted_at
                if elapsed < self.config.duplicate_suppress_seconds:
                    LOGGER.info("Ignoring duplicate hardware barcode/order number: %s", value)
                    return

            self._last_accepted_value = value
            self._last_accepted_at = now
            self._read_count += 1
            self._last_result = value
            self._results.append(value)

        LOGGER.info("Hardware scanner read barcode/order number: %s", value)

    def _resolve_device(self) -> str | None:
        configured_device = self.config.device.strip()
        if configured_device.lower() != "auto":
            return configured_device

        candidates: set[str] = set()
        for pattern in AUTO_DEVICE_PATTERNS:
            candidates.update(glob.glob(pattern))

        if not candidates:
            return None

        return sorted(candidates, key=_device_sort_key)[0]

    def _set_connected(self, connected: bool, device: str | None) -> None:
        with self._lock:
            self._connected = connected
            self._device = device


def _device_sort_key(path: str) -> tuple[int, str]:
    lower_path = path.lower()
    score = 50

    if lower_path.startswith("/dev/serial/by-id/"):
        score = 20
    elif lower_path.startswith("/dev/ttyacm"):
        score = 30
    elif lower_path.startswith("/dev/ttyusb"):
        score = 60

    if any(hint in lower_path for hint in SCANNER_DEVICE_HINTS):
        score -= 30
    if any(hint in lower_path for hint in MODEM_DEVICE_HINTS):
        score += 40

    return score, path


def _read_timeout(line_idle_seconds: float) -> float:
    if line_idle_seconds <= 0:
        return 0.2
    return min(0.2, line_idle_seconds)


def _configure_serial(file_descriptor: int, baudrate: int) -> None:
    try:
        import termios
    except Exception:
        return

    baud_constant = getattr(termios, f"B{baudrate}", None)
    if baud_constant is None:
        LOGGER.warning("Cannot set unsupported serial baudrate %s; using device default", baudrate)
        return

    attrs = termios.tcgetattr(file_descriptor)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] |= termios.CLOCAL | termios.CREAD
    attrs[2] &= ~termios.PARENB
    attrs[2] &= ~termios.CSTOPB
    attrs[2] &= ~termios.CSIZE
    attrs[2] |= termios.CS8
    if hasattr(termios, "CRTSCTS"):
        attrs[2] &= ~termios.CRTSCTS
    attrs[3] = 0
    attrs[4] = baud_constant
    attrs[5] = baud_constant
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(file_descriptor, termios.TCSANOW, attrs)
