"""Tests for the scheduled restart controller and its schedule validation."""

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from enshctl.lifecycle.auto_restart import (
    AutoRestartController,
    start_auto_restart,
)
from enshctl.scheduling import parse_schedule
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


class _Harness:
    def __init__(self, *, wall_start: datetime | None = None, players: bool = False) -> None:
        self.monotonic = 0.0
        self.wall_start = wall_start or datetime(2026, 5, 30, 8, 0, tzinfo=UTC)
        self.players = players
        self.requests = 0
        self.requested_at: float | None = None
        self.stop_event = threading.Event()
        self.on_wait: Callable[[_Harness], None] | None = None

    def clock(self) -> float:
        return self.monotonic

    def wall(self) -> datetime:
        return self.wall_start + timedelta(seconds=self.monotonic)

    def players_present(self) -> bool:
        return self.players

    def request(self) -> None:
        self.requests += 1
        self.requested_at = self.monotonic

    def wait(self, event: threading.Event, timeout: float) -> bool:
        self.monotonic += max(timeout, 0.0)
        if self.on_wait is not None:
            self.on_wait(self)
        return event.is_set()


def _controller(harness: _Harness, *, expression: str, max_delay: int = 3600) -> AutoRestartController:
    return AutoRestartController(
        schedule=parse_schedule(expression),
        expression=expression,
        max_delay=max_delay,
        players_present=harness.players_present,
        request_restart=harness.request,
        clock=harness.clock,
        wall_clock=harness.wall,
        wait=harness.wait,
    )


def test_disabled_starts_no_controller() -> None:
    # GIVEN Auto Restart disabled
    settings = _settings(auto_restart_enabled=False, auto_restart_cron="@every 24h")

    # WHEN starting the controller
    thread = start_auto_restart(
        settings,
        stop_event=threading.Event(),
        players_present=lambda: False,
        request_restart=lambda: None,
    )

    # THEN no thread starts
    assert thread is None


def test_empty_schedule_logs_an_error_and_starts_nothing(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an enabled controller with no schedule
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="")

    # WHEN starting the controller
    with caplog.at_level("ERROR", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=threading.Event(),
            players_present=lambda: False,
            request_restart=lambda: None,
        )

    # THEN it fails closed with an error naming the setting
    assert thread is None
    assert "AUTO_RESTART_CRON" in caplog.text


def test_invalid_schedule_logs_an_error_and_starts_nothing(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an enabled controller with a malformed schedule
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="not a cron")

    # WHEN starting the controller
    with caplog.at_level("ERROR", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=threading.Event(),
            players_present=lambda: False,
            request_restart=lambda: None,
        )

    # THEN it fails closed with an error naming the setting
    assert thread is None
    assert "AUTO_RESTART_CRON" in caplog.text


def test_impossible_schedule_logs_an_error_and_starts_nothing(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an enabled controller with a schedule that never occurs
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="0 0 30 2 *")

    # WHEN starting the controller
    with caplog.at_level("ERROR", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=threading.Event(),
            players_present=lambda: False,
            request_restart=lambda: None,
            wall_clock=lambda: datetime(2026, 5, 30, 8, 0, tzinfo=UTC),
        )

    # THEN it fails closed instead of waiting forever
    assert thread is None
    assert "no trigger" in caplog.text


def test_frequent_schedule_warns_and_starts(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a schedule that runs sooner than the warning threshold
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="@every 5m")
    stop_event = threading.Event()
    stop_event.set()

    # WHEN starting the controller
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=stop_event,
            players_present=lambda: False,
            request_restart=lambda: None,
        )

    # THEN it warns but still starts
    assert thread is not None
    thread.join(timeout=1)
    assert "very frequent" in caplog.text


def test_rollback_suppresses_the_controller_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a valid schedule while rollback is active
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="@every 24h")

    # WHEN starting the controller
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=threading.Event(),
            players_present=lambda: False,
            request_restart=lambda: None,
            rollback_active=True,
        )

    # THEN no controller starts and the suppression is warned
    assert thread is None
    assert "disabled while auto rollback is active" in caplog.text


def test_rollback_does_not_hide_an_invalid_schedule(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an invalid schedule while rollback is active
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="")

    # WHEN starting the controller
    with caplog.at_level("ERROR", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=threading.Event(),
            players_present=lambda: False,
            request_restart=lambda: None,
            rollback_active=True,
        )

    # THEN the invalid configuration is still reported
    assert thread is None
    assert "AUTO_RESTART_CRON" in caplog.text


def test_valid_schedule_logs_the_next_run(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a daily 9 AM schedule and a clock at 8 AM
    settings = _settings(auto_restart_enabled=True, auto_restart_cron="0 9 * * *")
    stop_event = threading.Event()
    stop_event.set()

    # WHEN starting the controller
    with caplog.at_level("INFO", logger="enshctl.lifecycle.auto_restart"):
        thread = start_auto_restart(
            settings,
            stop_event=stop_event,
            players_present=lambda: False,
            request_restart=lambda: None,
            wall_clock=lambda: datetime(2026, 5, 30, 8, 0, tzinfo=UTC),
        )

    # THEN the startup line names the schedule and next run
    assert thread is not None
    thread.join(timeout=1)
    assert "0 9 * * *" in caplog.text
    assert "next run in 1h" in caplog.text


def test_cron_restart_fires_at_the_scheduled_minute() -> None:
    # GIVEN a daily 9 AM schedule and a clock at 8 AM
    harness = _Harness()
    controller = _controller(harness, expression="0 9 * * *")

    # WHEN the controller runs
    thread = controller.start(harness.stop_event)
    thread.join(timeout=1)

    # THEN the restart fires one hour after launch, not on a later day
    assert harness.requests == 1
    assert harness.requested_at == 3600.0


def test_due_restart_requests_when_no_players_are_present() -> None:
    # GIVEN an elapsed schedule that becomes due with an empty server
    harness = _Harness()
    controller = _controller(harness, expression="@every 10s")

    # WHEN the controller runs
    thread = controller.start(harness.stop_event)
    thread.join(timeout=1)

    # THEN it requests one restart
    assert harness.requests == 1


def test_players_delay_the_restart_until_they_leave(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a due restart while players are online
    harness = _Harness(players=True)
    controller = _controller(harness, expression="@every 10s", max_delay=60)

    def _players_leave(state: _Harness) -> None:
        if state.monotonic >= 20:
            state.players = False

    harness.on_wait = _players_leave

    # WHEN the controller runs
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.auto_restart"):
        thread = controller.start(harness.stop_event)
        thread.join(timeout=1)

    # THEN the restart waits and then requests when the roster clears
    assert harness.requests == 1
    assert "waiting up to 60s" in caplog.text


def test_grace_expiry_requests_the_restart(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN players who stay online beyond a short grace window
    harness = _Harness(players=True)
    controller = _controller(harness, expression="@every 10s", max_delay=5)

    # WHEN the controller runs
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.auto_restart"):
        thread = controller.start(harness.stop_event)
        thread.join(timeout=1)

    # THEN the restart proceeds at the deadline with a warning
    assert harness.requests == 1
    assert "grace window expired" in caplog.text


def test_zero_grace_restarts_immediately_with_players() -> None:
    # GIVEN players online and a zero grace window
    harness = _Harness(players=True)
    controller = _controller(harness, expression="@every 10s", max_delay=0)

    # WHEN the controller runs
    thread = controller.start(harness.stop_event)
    thread.join(timeout=1)

    # THEN the restart is requested at the due time
    assert harness.requests == 1


def test_shutdown_before_the_due_time_does_not_request() -> None:
    # GIVEN a controller whose stop event is already set
    harness = _Harness()
    harness.stop_event.set()
    controller = _controller(harness, expression="@every 10s")

    # WHEN the controller runs
    thread = controller.start(harness.stop_event)
    thread.join(timeout=1)

    # THEN no restart is requested
    assert harness.requests == 0


def test_shutdown_during_the_grace_window_does_not_request() -> None:
    # GIVEN a due restart waiting for players and a shutdown during the wait
    harness = _Harness(players=True)
    controller = _controller(harness, expression="@every 10s", max_delay=60)

    def _shutdown(state: _Harness) -> None:
        if state.monotonic >= 12:
            state.stop_event.set()

    harness.on_wait = _shutdown

    # WHEN the controller runs
    thread = controller.start(harness.stop_event)
    thread.join(timeout=1)

    # THEN no restart is requested
    assert harness.requests == 0


def test_controller_failure_is_logged_without_a_restart(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a presence probe that fails unexpectedly
    harness = _Harness()

    def _fail() -> bool:
        msg = "presence probe failed"
        raise RuntimeError(msg)

    controller = AutoRestartController(
        schedule=parse_schedule("@every 10s"),
        expression="@every 10s",
        max_delay=60,
        players_present=_fail,
        request_restart=harness.request,
        clock=harness.clock,
        wall_clock=harness.wall,
        wait=harness.wait,
    )

    # WHEN the controller runs
    with caplog.at_level("ERROR", logger="enshctl.lifecycle.auto_restart"):
        thread = controller.start(harness.stop_event)
        thread.join(timeout=1)

    # THEN the failure is logged and no restart is requested
    assert harness.requests == 0
    assert "controller failed" in caplog.text
