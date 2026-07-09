from __future__ import annotations

import re
from datetime import datetime

SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_order_number(order_number: str) -> str:
    sanitized = SAFE_CHARS.sub("_", order_number.strip()).strip("._-")
    if not sanitized:
        raise ValueError("Order number is empty after sanitizing")
    return sanitized[:80]


def build_video_name(order_number: str, extension: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{sanitize_order_number(order_number)}_{timestamp}{ext}"
