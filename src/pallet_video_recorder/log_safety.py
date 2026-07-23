from __future__ import annotations

import hashlib


def safe_scan_value(value: str | None, *, max_visible: int = 80) -> str:
    if not value:
        return "-"

    if value.startswith("PALLETPROOF") or len(value) > max_visible:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        return f"<redacted len={len(value)} sha256={digest}>"

    return value
