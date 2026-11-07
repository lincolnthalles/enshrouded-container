"""Cron scheduling — minute-level trigger parsing for background schedulers."""

import logging
import time
from contextlib import suppress

logger = logging.getLogger(__name__)


def parse_cron(
    expr: str,
    *,
    fallback: float = 1200.0,
    now: time.struct_time | None = None,
) -> float | None:
    """Parse a cron expression to seconds until next trigger. Supports '*/N' syntax."""
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
