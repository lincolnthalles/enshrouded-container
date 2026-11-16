"""Schedule parsing and next-trigger timing for background controllers."""

import logging
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)

_EVERY_PATTERN = re.compile(r"^@every\s+(?P<amount>[0-9]+)(?P<unit>[smhd])$")
_ASCII_DIGITS = re.compile(r"^[0-9]+$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 7),
}
_MAX_SEARCH_DAYS = 366 * 5


def parse_cron(
    expr: str,
    *,
    fallback: float = 1200.0,
    now: time.struct_time | None = None,
) -> float | None:
    """Parse the legacy minute-level interval used by Backups, Auto Update, and Rollback.

    Restart schedules use `parse_schedule`; this function intentionally ignores non-minute fields.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        logger.error("Invalid cron expression: %s", expr)
        return None

    minute_part, hour_part, day_part, month_part, weekday_part = parts
    unsupported = []
    if hour_part != "*":
        unsupported.append(f"hour={hour_part}")
    if day_part != "*":
        unsupported.append(f"day={day_part}")
    if month_part != "*":
        unsupported.append(f"month={month_part}")
    if weekday_part != "*":
        unsupported.append(f"weekday={weekday_part}")
    if unsupported:
        logger.warning(
            "Cron expression has unsupported fields (%s); only minute-level scheduling is supported. "
            "Ignoring non-minute fields.",
            ", ".join(unsupported),
        )

    local_now = time.localtime() if now is None else now
    if minute_part.startswith("*/"):
        with suppress(ValueError):
            interval = int(minute_part[2:])
            if interval < 1:
                msg = f"Non-positive interval in cron expression: {expr}"
                raise ValueError(msg)
            remaining = (interval - local_now.tm_min % interval) * 60 - local_now.tm_sec
            return float(max(remaining, 60))

    if minute_part.isdigit():
        with suppress(ValueError):
            target_min = int(minute_part)
            remaining = (target_min - local_now.tm_min) % 60
            if remaining == 0:
                remaining = 60
            return float(remaining * 60)

    logger.warning("Unsupported cron expression; using %.0f seconds: %s", fallback, expr)
    return fallback


class Schedule(Protocol):
    """One parsed restart schedule."""

    def next_delay(self, *, now: datetime, elapsed: float) -> float | None: ...


@dataclass(frozen=True)
class EverySchedule:
    """A fixed interval measured from the current server launch."""

    interval: float

    def next_delay(self, *, now: datetime, elapsed: float) -> float:
        del now
        return max(self.interval - elapsed, 0.0)


@dataclass(frozen=True)
class CronSchedule:
    """A parsed wall-clock cron schedule."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    is_day_restricted: bool
    is_weekday_restricted: bool

    def next_delay(self, *, now: datetime, elapsed: float) -> float | None:
        del elapsed
        start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        day = start.replace(hour=0, minute=0)
        horizon = now + timedelta(days=_MAX_SEARCH_DAYS)
        for _ in range(_MAX_SEARCH_DAYS + 1):
            if day > horizon:
                return None
            if self._day_matches(day):
                candidate = self._first_time_on(day, start)
                if candidate is not None:
                    return (candidate - now).total_seconds()
            day += timedelta(days=1)
        return None

    def _day_matches(self, day: datetime) -> bool:
        if day.month not in self.months:
            return False
        day_match = day.day in self.days
        weekday_match = _cron_weekday(day) in self.weekdays
        if self.is_day_restricted and self.is_weekday_restricted:
            return day_match or weekday_match
        return day_match and weekday_match

    def _first_time_on(self, day: datetime, start: datetime) -> datetime | None:
        for hour in sorted(self.hours):
            for minute in sorted(self.minutes):
                candidate = day.replace(hour=hour, minute=minute)
                if candidate >= start:
                    return candidate
        return None


def parse_schedule(expr: str) -> Schedule:
    """Parse one restart schedule, raising ValueError when it is invalid."""
    original = expr.strip()
    if not original:
        msg = "Invalid restart schedule: AUTO_RESTART_CRON is empty"
        raise ValueError(msg)
    text = original.lower()
    try:
        if text.startswith("@every"):
            return _parse_every(text)
        return _parse_full_cron(text)
    except (ValueError, OverflowError) as exc:
        msg = f"Invalid AUTO_RESTART_CRON {original!r}: {exc}"
        raise ValueError(msg) from exc


def format_next_run(seconds: float) -> str:
    """Human countdown for the next scheduled run."""
    total = max(int(seconds), 60)
    hours, remainder = divmod(total, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0 and minutes > 0:
        return f"in {hours}h {minutes}m"
    if hours > 0:
        return f"in {hours}h"
    return f"in {minutes}m" if minutes > 0 else "in 1m"


def _parse_every(text: str) -> EverySchedule:
    match = _EVERY_PATTERN.fullmatch(text)
    if match is None:
        msg = f"Invalid @every schedule: {text!r}"
        raise ValueError(msg)
    amount = int(match["amount"])
    if amount <= 0:
        msg = f"@every interval must be positive: {text!r}"
        raise ValueError(msg)
    return EverySchedule(float(amount * _UNIT_SECONDS[match["unit"]]))


def _parse_full_cron(text: str) -> CronSchedule:
    parts = text.split()
    if len(parts) != 5:
        msg = f"Cron expression must have five fields: {text!r}"
        raise ValueError(msg)
    minute_part, hour_part, day_part, month_part, weekday_part = parts
    days = frozenset(_parse_field(day_part, "day"))
    weekdays = frozenset(0 if value == 7 else value for value in _parse_field(weekday_part, "weekday"))
    return CronSchedule(
        minutes=frozenset(_parse_field(minute_part, "minute")),
        hours=frozenset(_parse_field(hour_part, "hour")),
        days=days,
        months=frozenset(_parse_field(month_part, "month")),
        weekdays=weekdays,
        is_day_restricted=days != frozenset(range(1, 32)),
        is_weekday_restricted=weekdays != frozenset(range(7)),
    )


def _parse_field(raw: str, name: str) -> set[int]:
    low, high = _FIELD_RANGES[name]
    values: set[int] = set()
    for item in raw.split(","):
        values.update(_parse_item(item.strip(), low, high, name))
    if not values:
        msg = f"Empty {name} field: {raw!r}"
        raise ValueError(msg)
    return values


def _parse_item(item: str, low: int, high: int, name: str) -> set[int]:
    if not item:
        msg = f"Empty item in {name} field"
        raise ValueError(msg)
    base, separator, raw_step = item.partition("/")
    if separator:
        if not _ASCII_DIGITS.fullmatch(raw_step) or int(raw_step) <= 0:
            msg = f"Invalid step in {name} field: {item!r}"
            raise ValueError(msg)
        step = int(raw_step)
    else:
        step = 1
    if base == "*":
        start, end = low, high
    elif "-" in base:
        raw_start, range_separator, raw_end = base.partition("-")
        if not range_separator or not _ASCII_DIGITS.fullmatch(raw_start) or not _ASCII_DIGITS.fullmatch(raw_end):
            msg = f"Invalid range in {name} field: {item!r}"
            raise ValueError(msg)
        start, end = int(raw_start), int(raw_end)
    elif _ASCII_DIGITS.fullmatch(base):
        if separator:
            msg = f"Step requires a range or * in {name} field: {item!r}"
            raise ValueError(msg)
        start = end = int(base)
    else:
        msg = f"Invalid value in {name} field: {item!r}"
        raise ValueError(msg)
    if start < low or end > high or start > end:
        msg = f"Value out of range in {name} field: {item!r}"
        raise ValueError(msg)
    return set(range(start, end + 1, step))


def _cron_weekday(day: datetime) -> int:
    return (day.weekday() + 1) % 7
