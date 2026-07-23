from __future__ import annotations

import re
from datetime import datetime

SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_filename_part(value: str, name: str, max_length: int = 80) -> str:
    sanitized = SAFE_CHARS.sub("_", value.strip()).strip("._-")
    if not sanitized:
        raise ValueError(f"{name} is empty after sanitizing")
    return sanitized[:max_length]


def sanitize_scanned_id(scanned_id: str) -> str:
    return sanitize_filename_part(scanned_id, "Scanned ID")


def sanitize_order_number(order_number: str) -> str:
    return sanitize_scanned_id(order_number)


def sanitize_serial_number(serial_number: str) -> str:
    return sanitize_filename_part(serial_number, "Serial number", max_length=64)


def build_video_name(
    scanned_id: str,
    extension: str,
    now: datetime | None = None,
    serial_number: str = "",
) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    ext = extension if extension.startswith(".") else f".{extension}"
    if serial_number:
        return f"{sanitize_serial_number(serial_number)}_{sanitize_scanned_id(scanned_id)}_{timestamp}{ext}"
    return f"{sanitize_scanned_id(scanned_id)}_{timestamp}{ext}"
