"""Tests for restart schedule parsing and next-trigger timing."""

from datetime import UTC, datetime

import pytest
from enshctl.scheduling import EverySchedule, format_next_run, parse_schedule


def _at(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def test_every_schedule_measures_from_the_current_launch() -> None:
    # GIVEN a 24-hour interval schedule
    schedule = parse_schedule("@every 24h")

    # WHEN asking for the next delay at different elapsed times
    # THEN the remaining interval counts down from the launch
    assert schedule == EverySchedule(86400.0)
    assert schedule.next_delay(now=_at(2026, 5, 30, 9), elapsed=0.0) == 86400.0
    assert schedule.next_delay(now=_at(2026, 5, 30, 9), elapsed=3600.0) == 82800.0
    assert schedule.next_delay(now=_at(2026, 5, 30, 9), elapsed=86400.0) == 0.0


def test_every_schedule_accepts_friendly_units_and_case() -> None:
    # GIVEN minute and day units in mixed case
    # WHEN parsing
    # THEN both convert to seconds
    assert parse_schedule("@every 90m").next_delay(now=_at(2026, 5, 30), elapsed=0.0) == 5400.0
    assert parse_schedule("@EVERY 1D").next_delay(now=_at(2026, 5, 30), elapsed=0.0) == 86400.0


def test_cron_schedule_uses_the_next_wall_clock_trigger() -> None:
    # GIVEN a daily 9 AM schedule and a clock before the trigger
    schedule = parse_schedule("0 9 * * *")

    # WHEN asking for the next delay
    # THEN the trigger is thirty minutes away
    assert schedule.next_delay(now=_at(2026, 5, 30, 8, 30), elapsed=0.0) == 1800.0


def test_cron_schedule_is_strictly_after_the_current_minute() -> None:
    # GIVEN a clock exactly on the scheduled minute
    schedule = parse_schedule("0 9 * * *")

    # WHEN asking for the next delay
    # THEN the trigger is the next day, not now
    assert schedule.next_delay(now=_at(2026, 5, 30, 9, 0), elapsed=0.0) == 86400.0


def test_cron_schedule_handles_seconds_within_the_current_minute() -> None:
    # GIVEN a clock part-way through a minute before the next five-minute boundary
    schedule = parse_schedule("*/5 * * * *")

    # WHEN asking for the next delay
    # THEN the trigger aligns to the boundary and accounts for the seconds
    assert schedule.next_delay(now=_at(2026, 5, 30, 14, 37, 30), elapsed=0.0) == 150.0


def test_cron_schedule_accepts_lists_ranges_and_steps() -> None:
    # GIVEN a schedule with a minute list, an hour range, and a day step
    schedule = parse_schedule("15,45 8-10 */1 * *")

    # WHEN asking from a time before the first matching hour
    # THEN the first listed minute in the range is selected
    assert schedule.next_delay(now=_at(2026, 5, 30, 7, 0), elapsed=0.0) == 4500.0
    # AND a later request picks the next listed minute
    assert schedule.next_delay(now=_at(2026, 5, 30, 8, 20), elapsed=0.0) == 1500.0


def test_cron_schedule_treats_seven_as_sunday() -> None:
    # GIVEN a Sunday schedule using the 7 alias and a Saturday clock
    schedule = parse_schedule("0 9 * * 7")

    # WHEN asking for the next delay
    # THEN Sunday morning is selected
    assert schedule.next_delay(now=_at(2026, 5, 30, 10, 0), elapsed=0.0) == 82800.0


def test_cron_schedule_ors_restricted_day_and_weekday_fields() -> None:
    # GIVEN both day-of-month and day-of-week restricted
    schedule = parse_schedule("0 9 2 * 1")

    # WHEN asking from a Saturday before the next Monday
    # THEN either field may match, so Monday wins over the second of the month
    assert schedule.next_delay(now=_at(2026, 5, 30, 10, 0), elapsed=0.0) == 2 * 86400 - 3600


def test_cron_schedule_treats_an_all_value_field_as_unrestricted() -> None:
    # GIVEN day fields that cover every possible value through a step or range
    daily_day = parse_schedule("0 9 */1 * 1")
    ranged_day = parse_schedule("0 9 1-31 * 1")

    # WHEN asking from a Saturday before the next Monday
    # THEN only Monday matches; the all-value day field does not OR in every day
    assert daily_day.next_delay(now=_at(2026, 5, 30, 10, 0), elapsed=0.0) == 2 * 86400 - 3600
    assert ranged_day.next_delay(now=_at(2026, 5, 30, 10, 0), elapsed=0.0) == 2 * 86400 - 3600


def test_cron_schedule_without_a_future_trigger_has_no_delay() -> None:
    # GIVEN February 30, which never occurs
    schedule = parse_schedule("0 0 30 2 *")

    # WHEN asking for the next delay from a real launch time
    # THEN no trigger resolves within the search horizon
    assert schedule.next_delay(now=_at(2026, 5, 30), elapsed=0.0) is None


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "@every",
        "@every 0h",
        "@every 24",
        "@every 24x",
        "not a cron",
        "60 * * * *",
        "*/0 * * * *",
        "0 24 * * *",
        "0 9 0 * *",
        "0 9 * 13 *",
        "0 9 * * 8",
        "0 9 1-0 * *",
        "0 9 * * MON",
        "0 9 * * 1,",
        "5/2 * * * *",
        f"{chr(0x0665)} * * * *",
        f"@every {'9' * 400}h",
    ],
)
def test_invalid_schedules_are_rejected(expression: str) -> None:
    # GIVEN an invalid or empty schedule expression
    # WHEN parsing
    # THEN it is rejected before any restart is scheduled
    with pytest.raises(ValueError, match="AUTO_RESTART_CRON"):
        _ = parse_schedule(expression)


def test_format_next_run_counts_down() -> None:
    # GIVEN wall-clock countdowns
    # WHEN formatting the next run
    # THEN hour and minute buckets are humanized
    assert format_next_run(3600.0) == "in 1h"
    assert format_next_run(5400.0) == "in 1h 30m"
    assert format_next_run(120.0) == "in 2m"
