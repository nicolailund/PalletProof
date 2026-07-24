from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_ACTIVE_DAYS = (1, 2, 3, 4, 5, 6, 7)


@dataclass(frozen=True)
class ScannerSchedule:
    enabled: bool = False
    active_start: time = time(6, 0)
    active_end: time = time(18, 0)
    active_days: tuple[int, ...] = DEFAULT_ACTIVE_DAYS
    timezone: str = "Europe/Copenhagen"

    @classmethod
    def from_cloud(cls, value: object) -> "ScannerSchedule":
        if not isinstance(value, dict):
            return cls()

        active_days = _active_days(value.get("active_days"))
        return cls(
            enabled=bool(value.get("enabled", False)),
            active_start=_parse_time(value.get("active_start"), time(6, 0)),
            active_end=_parse_time(value.get("active_end"), time(18, 0)),
            active_days=active_days,
            timezone=_timezone_name(value.get("timezone")),
        )

    def is_active(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return True

        local_now = _local_datetime(now, self.timezone)
        current_time = local_now.time().replace(tzinfo=None)
        current_day = local_now.isoweekday()
        previous_day = 7 if current_day == 1 else current_day - 1

        if self.active_start == self.active_end:
            return current_day in self.active_days

        if self.active_start < self.active_end:
            return current_day in self.active_days and self.active_start <= current_time < self.active_end

        return (current_day in self.active_days and current_time >= self.active_start) or (
            previous_day in self.active_days and current_time < self.active_end
        )


def _parse_time(value: object, fallback: time) -> time:
    if not isinstance(value, str):
        return fallback
    parts = value.strip().split(":")
    if len(parts) < 2:
        return fallback
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return time(hour, minute)


def _active_days(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return DEFAULT_ACTIVE_DAYS
    days = sorted({int(day) for day in value if isinstance(day, int | float) and 1 <= int(day) <= 7})
    return tuple(days) or DEFAULT_ACTIVE_DAYS


def _timezone_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Europe/Copenhagen"
    try:
        ZoneInfo(value.strip())
    except ZoneInfoNotFoundError:
        return _local_timezone_name()
    return value.strip()


def _local_datetime(now: datetime | None, timezone_name: str) -> datetime:
    zone = _zone(timezone_name)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def _zone(timezone_name: str) -> tzinfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def _local_timezone_name() -> str:
    local_zone = datetime.now().astimezone().tzinfo
    return getattr(local_zone, "key", None) or getattr(local_zone, "zone", None) or str(local_zone) or "UTC"
