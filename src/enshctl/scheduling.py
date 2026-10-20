"""Cron scheduling — minute-level trigger parsing for the backup scheduler."""

import logging
import time
from contextlib import suppress

logger = logging.getLogger(__name__)


def parse_cron(expr: str) -> float | None:
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

    if minute_part.startswith("*/"):
        with suppress(ValueError):
            interval = int(minute_part[2:])
            now = time.localtime()
            remaining = (interval - now.tm_min % interval) * 60 - now.tm_sec
            return float(max(remaining, 60))

    if minute_part.isdigit():
        with suppress(ValueError):
            target_min = int(minute_part)
            now = time.localtime()
            current_min = now.tm_min
            remaining = (target_min - current_min) % 60
            if remaining == 0:
                remaining = 60
            return float(remaining * 60)

    logger.warning("Unsupported cron expression, defaulting to 20 minutes: %s", expr)
    return 1200.0
