from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import glob
import logging
import re
import select
import struct
import threading
import time
from typing import BinaryIO

from .barcode import _has_valid_gs1_ai01
from .config import HardwareScannerConfig
from .log_safety import safe_scan_value

LOGGER = logging.getLogger(__name__)

AUTO_DEVICE_PATTERNS = (
    "/dev/serial/by-id/*",
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
)

AUTO_HID_PATTERNS = (
    "/dev/input/by-id/*event-kbd",
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

EV_KEY = 1
KEY_ENTER = 28
KEY_TAB = 15
KEY_BACKSPACE = 14
KEY_KPENTER = 96
SHIFT_CODES = {42, 54}
LINE_COMMIT_KEYS = {KEY_ENTER, KEY_KPENTER, KEY_TAB}
LINUX_INPUT_EVENT = struct.Struct("llHHi")

HID_KEYMAP: dict[int, tuple[str, str]] = {
    2: ("1", "!"),
    3: ("2", "@"),
    4: ("3", "#"),
    5: ("4", "$"),
    6: ("5", "%"),
    7: ("6", "^"),
    8: ("7", "&"),
    9: ("8", "*"),
    10: ("9", "("),
    11: ("0", ")"),
    12: ("-", "_"),
    13: ("=", "+"),
    16: ("q", "Q"),
    17: ("w", "W"),
    18: ("e", "E"),
    19: ("r", "R"),
    20: ("t", "T"),
    21: ("y", "Y"),
    22: ("u", "U"),
    23: ("i", "I"),
    24: ("o", "O"),
    25: ("p", "P"),
    26: ("[", "{"),
    27: ("]", "}"),
    30: ("a", "A"),
    31: ("s", "S"),
    32: ("d", "D"),
    33: ("f", "F"),
    34: ("g", "G"),
    35: ("h", "H"),
    36: ("j", "J"),
    37: ("k", "K"),
    38: ("l", "L"),
    39: (";", ":"),
    40: ("'", '"'),
    41: ("`", "~"),
    43: ("\\", "|"),
    44: ("z", "Z"),
    45: ("x", "X"),
    46: ("c", "C"),
    47: ("v", "V"),
    48: ("b", "B"),
    49: ("n", "N"),
    50: ("m", "M"),
    51: (",", "<"),
    52: (".", ">"),
    53: ("/", "?"),
    55: ("*", "*"),
    57: (" ", " "),
    74: ("-", "-"),
    78: ("+", "+"),
    79: ("1", "1"),
    80: ("2", "2"),
    81: ("3", "3"),
    82: ("0", "0"),
    83: (".", "."),
    71: ("7", "7"),
    72: ("8", "8"),
    73: ("9", "9"),
    75: ("4", "4"),
    76: ("5", "5"),
    77: ("6", "6"),
    98: ("/", "/"),
}


@dataclass(frozen=True)
class HardwareScannerStats:
    enabled: bool
    connected: bool
    device: str | None
    read_count: int
    queued_results: int
    last_result: str | None


@dataclass(frozen=True)
class ScannerDevice:
    mode: str
    path: str


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
        self._trigger_event = threading.Event()
        self._trigger_thread: threading.Thread | None = None
        self._trigger_output = None

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
        self._start_trigger_thread()

    def stop(self) -> None:
        self._stop_event.set()
        self._trigger_event.clear()
        if self._trigger_thread is not None:
            self._trigger_thread.join(timeout=5)
            self._trigger_thread = None
        if self._trigger_output is not None:
            self._trigger_output.close()
            self._trigger_output = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def enable_triggering(self) -> None:
        if self.config.trigger_gpio_enabled:
            self._trigger_event.set()

    def disable_triggering(self) -> None:
        self._trigger_event.clear()
        self._set_trigger_output(False)

    def poll(self) -> str | None:
        with self._lock:
            if not self._results:
                return None
            return self._results.popleft()

    def discard_pending_results(self) -> int:
        with self._lock:
            count = len(self._results)
            self._results.clear()
            return count

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
            LOGGER.warning("Ignoring hardware barcode outside accepted pattern: %s", safe_scan_value(value))
            return None
        if self.config.validate_gs1_ai01_check_digit and not _has_valid_gs1_ai01(value):
            LOGGER.warning("Ignoring GS1 AI(01) barcode with invalid check digit: %s", safe_scan_value(value))
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
                    "No hardware barcode scanner device found; retrying in %.1fs",
                    self.config.reconnect_seconds,
                )
                self._stop_event.wait(self.config.reconnect_seconds)
                continue

            try:
                if device.mode == "hid_keyboard":
                    self._read_hid_device(device.path)
                else:
                    self._read_serial_device(device.path)
            except PermissionError as exc:
                if not self._stop_event.is_set():
                    LOGGER.warning(
                        "Cannot read hardware barcode scanner %s; check service user input-device permissions: %s",
                        device.path,
                        exc,
                    )
            except Exception as exc:
                if not self._stop_event.is_set():
                    LOGGER.warning(
                        "Hardware barcode scanner disconnected or failed on %s: %s",
                        device.path,
                        exc,
                    )
            finally:
                self._set_connected(False, device.path)

            self._stop_event.wait(self.config.reconnect_seconds)

    def _read_serial_device(self, device: str) -> None:
        LOGGER.info("Opening hardware barcode scanner on %s at %s baud", device, self.config.baudrate)
        with open(device, "rb", buffering=0) as handle:
            _configure_serial(handle.fileno(), self.config.baudrate)
            self._set_connected(True, device)
            LOGGER.info("Hardware barcode scanner ready on %s", device)
            self._read_serial_loop(handle)

    def _read_hid_device(self, device: str) -> None:
        LOGGER.info("Opening HID keyboard barcode scanner on %s", device)
        with open(device, "rb", buffering=0) as handle:
            self._set_connected(True, device)
            LOGGER.info("HID keyboard barcode scanner ready on %s", device)
            self._read_hid_loop(handle)

    def _read_serial_loop(self, handle: BinaryIO) -> None:
        buffer = bytearray()
        max_buffer_size = max(self.config.max_chars * 4, 256)
        last_byte_at: float | None = None

        while not self._stop_event.is_set():
            timeout = _read_timeout(self.config.line_idle_seconds)
            ready, _, _ = select.select([handle], [], [], timeout)
            if not ready:
                if self._is_idle_line_complete(bool(buffer), last_byte_at):
                    self._handle_serial_line(buffer)
                    buffer.clear()
                    last_byte_at = None
                continue

            chunk = handle.read(64)
            if not chunk:
                raise OSError("serial device returned EOF")

            for byte in chunk:
                if byte in (10, 13):
                    self._handle_serial_line(buffer)
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

    def _read_hid_loop(self, handle: BinaryIO) -> None:
        buffer: list[str] = []
        shift_codes: set[int] = set()
        last_key_at: float | None = None

        while not self._stop_event.is_set():
            timeout = _read_timeout(self.config.line_idle_seconds)
            ready, _, _ = select.select([handle], [], [], timeout)
            if not ready:
                if self._is_idle_line_complete(bool(buffer), last_key_at):
                    self._handle_text_line("".join(buffer))
                    buffer.clear()
                    last_key_at = None
                continue

            data = handle.read(LINUX_INPUT_EVENT.size)
            if not data:
                raise OSError("HID input device returned EOF")
            if len(data) != LINUX_INPUT_EVENT.size:
                continue

            _, _, event_type, code, value = LINUX_INPUT_EVENT.unpack(data)
            if event_type != EV_KEY:
                continue

            if code in SHIFT_CODES:
                if value == 0:
                    shift_codes.discard(code)
                elif value == 1:
                    shift_codes.add(code)
                continue

            if value != 1:
                continue

            if code in LINE_COMMIT_KEYS:
                self._handle_text_line("".join(buffer))
                buffer.clear()
                last_key_at = None
                continue

            if code == KEY_BACKSPACE:
                if buffer:
                    buffer.pop()
                last_key_at = self._clock()
                continue

            character = _hid_key_to_char(code, shifted=bool(shift_codes))
            if character is None:
                continue

            buffer.append(character)
            last_key_at = self._clock()
            if len(buffer) > self.config.max_chars * 4:
                LOGGER.warning("Ignoring overlong HID hardware barcode scanner line")
                buffer.clear()
                last_key_at = None

    def _handle_serial_line(self, buffer: bytearray) -> None:
        if not buffer:
            return
        raw_value = bytes(buffer).decode("utf-8", errors="replace")
        self._handle_text_line(raw_value)

    def _handle_text_line(self, raw_value: str) -> None:
        value = self.normalize(raw_value)
        if value is not None:
            self._queue_value(value)

    def _is_idle_line_complete(self, has_buffer: bool, last_byte_at: float | None) -> bool:
        if not has_buffer or last_byte_at is None or self.config.line_idle_seconds <= 0:
            return False
        return self._clock() - last_byte_at >= self.config.line_idle_seconds

    def _queue_value(self, value: str) -> None:
        now = self._clock()
        with self._lock:
            if self._last_accepted_value == value:
                elapsed = now - self._last_accepted_at
                if elapsed < self.config.duplicate_suppress_seconds:
                    LOGGER.info("Ignoring duplicate hardware barcode/order number: %s", safe_scan_value(value))
                    return

            self._last_accepted_value = value
            self._last_accepted_at = now
            self._read_count += 1
            self._last_result = value
            self._results.append(value)

        LOGGER.info("Hardware scanner read barcode/order number: %s", safe_scan_value(value))

    def _resolve_device(self) -> ScannerDevice | None:
        configured_device = self.config.device.strip()
        if configured_device.lower() != "auto":
            return ScannerDevice(_configured_mode(configured_device, self.config.mode), configured_device)

        candidates: list[ScannerDevice] = []
        if self.config.mode in {"auto", "serial"}:
            for pattern in AUTO_DEVICE_PATTERNS:
                candidates.extend(ScannerDevice("serial", path) for path in glob.glob(pattern))
        if self.config.mode in {"auto", "hid_keyboard"}:
            for pattern in AUTO_HID_PATTERNS:
                candidates.extend(ScannerDevice("hid_keyboard", path) for path in glob.glob(pattern))

        if not candidates:
            return None

        return sorted(candidates, key=_device_sort_key)[0]

    def _set_connected(self, connected: bool, device: str | None) -> None:
        with self._lock:
            self._connected = connected
            self._device = device

    def _start_trigger_thread(self) -> None:
        if not self.config.trigger_gpio_enabled or self._trigger_thread is not None:
            return

        try:
            from gpiozero import OutputDevice

            self._trigger_output = OutputDevice(
                self.config.trigger_gpio_pin,
                active_high=self.config.trigger_active_high,
                initial_value=False,
            )
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            LOGGER.warning("GPIO scanner trigger unavailable: %s", exc)
            return

        self._trigger_thread = threading.Thread(
            target=self._run_trigger_loop,
            name="hardware-barcode-trigger",
            daemon=True,
        )
        self._trigger_thread.start()
        LOGGER.info(
            "Hardware barcode scanner GPIO trigger ready on GPIO%s every %.1fs",
            self.config.trigger_gpio_pin,
            self.config.trigger_interval_seconds,
        )

    def _run_trigger_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._trigger_event.wait(0.2):
                continue

            self._pulse_trigger()
            self._stop_event.wait(self.config.trigger_interval_seconds)

    def _pulse_trigger(self) -> None:
        if self._trigger_output is None:
            return
        try:
            self._set_trigger_output(True)
            deadline = self._clock() + self.config.trigger_pulse_seconds
            while not self._stop_event.is_set() and self._trigger_event.is_set():
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                self._stop_event.wait(min(0.05, remaining))
            self._set_trigger_output(False)
        except Exception as exc:  # pragma: no cover - Pi-only dependency
            LOGGER.warning("Could not pulse hardware barcode scanner trigger: %s", exc)

    def _set_trigger_output(self, active: bool) -> None:
        if self._trigger_output is None:
            return
        if active:
            self._trigger_output.on()
        else:
            self._trigger_output.off()


def _device_sort_key(device: ScannerDevice | str) -> tuple[int, str]:
    if isinstance(device, ScannerDevice):
        mode = device.mode
        path = device.path
    else:
        mode = _configured_mode(device, "auto")
        path = device

    lower_path = path.lower()
    score = 50

    if mode == "hid_keyboard":
        score = 15
    elif lower_path.startswith("/dev/serial/by-id/"):
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


def _configured_mode(device: str, configured_mode: str) -> str:
    if configured_mode in {"serial", "hid_keyboard"}:
        return configured_mode
    if device.startswith("/dev/input/"):
        return "hid_keyboard"
    return "serial"


def _hid_key_to_char(code: int, shifted: bool) -> str | None:
    values = HID_KEYMAP.get(code)
    if values is None:
        return None
    return values[1] if shifted else values[0]


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
