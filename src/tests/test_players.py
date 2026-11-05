"""Tests for player roster reporting."""

import threading
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from enshctl.lifecycle.players import PlayerReporter
from enshctl.presence import Player, PresenceEvent, PresenceSnapshot, PresenceTracker
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    import pytest

_ADD = "[I 00:00:01,000] [session] Remote player added. Player handle: {handle}"
_MACHINE = "[I 00:00:02,000] [server] Machine '1': Player '{handle}' logged in"
_NAME = "[I 00:00:03,000] [server] Player '{name}' logged in with Permissions:"
_REMOVED = "[I 00:00:04,300] [session] Player removed. Player handle: {handle}"


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _FakeStopEvent:
    def __init__(self) -> None:
        self._waits = 0

    def is_set(self) -> bool:
        return self._waits >= 2

    def wait(self, timeout: float) -> bool:
        _ = timeout
        self._waits += 1
        return self._waits >= 2


class _BlockingTracker:
    def __init__(self) -> None:
        self.observe_entered = threading.Event()
        self.release_observe = threading.Event()
        self.expired = threading.Event()

    def observe(self, line: str, now: float | None = None) -> tuple[PresenceEvent, ...]:
        del line, now
        self.observe_entered.set()
        assert self.release_observe.wait(timeout=1)
        return ()

    def expire(self, now: float | None = None) -> tuple[PresenceEvent, ...]:
        del now
        self.expired.set()
        return ()

    def snapshot(self) -> PresenceSnapshot:
        return PresenceSnapshot(())


def test_reporter_logs_join_with_handle_and_leave_with_name(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a reporter with roster output enabled
    clock = _FakeClock()
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_poll_interval=0), clock=clock)

    # WHEN the player joins, is named, and leaves
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        reporter.observe(_ADD.format(handle="0(0)"))
        clock.now = 1.0
        reporter.observe(_NAME.format(name="Morgan"))
        clock.now = 2.0
        reporter.observe(_REMOVED.format(handle="0(0)"))

    # THEN the join uses the handle and the leave uses the name
    assert "Player joined: 0(0)" in caplog.text
    assert "Player left: Morgan" in caplog.text


def test_summary_lists_names_in_first_add_order(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN two named players
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_poll_interval=0), clock=_FakeClock())
    reporter.observe(_ADD.format(handle="0(2)"))
    reporter.observe(_ADD.format(handle="0(10)"))
    reporter.observe(_NAME.format(name="Alice"))
    reporter.observe(_NAME.format(name="Bob"))

    # WHEN a summary is logged
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        reporter.log_summary()

    # THEN names follow first-add order
    assert "Players online: 2 - Alice, Bob" in caplog.text


def test_summary_uses_handles_for_unnamed_players(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN one unnamed player
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_poll_interval=0), clock=_FakeClock())
    reporter.observe(_ADD.format(handle="0(0)"))

    # WHEN a summary is logged
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        reporter.log_summary()

    # THEN the summary uses the handle
    assert "Players online: 1 - 0(0)" in caplog.text


def test_empty_summary(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an empty roster
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_poll_interval=0), clock=_FakeClock())

    # WHEN a summary is logged
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        reporter.log_summary()

    # THEN the empty summary is logged
    assert "Players online: 0" in caplog.text


def test_output_disabled_suppresses_roster_but_keeps_tracking(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a reporter with roster output disabled
    clock = _FakeClock()
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_log=False, player_poll_interval=60), clock=clock)

    # WHEN a player joins and is named
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        reporter.observe(_ADD.format(handle="0(0)"))
        clock.now = 1.0
        reporter.observe(_NAME.format(name="Morgan"))

    # THEN no roster lines are emitted but the tracker still holds the player
    assert "Player joined" not in caplog.text
    assert tracker.snapshot().players == (Player("0(0)", "Morgan"),)

    # AND a later removal is also tracked without output
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        clock.now = 2.0
        reporter.observe(_REMOVED.format(handle="0(0)"))
        reporter.log_summary()
    assert "Player left" not in caplog.text
    assert "Players online" not in caplog.text
    assert tracker.snapshot().players == ()


def test_warnings_survive_output_suppression(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN roster output disabled
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_log=False, player_poll_interval=60), clock=_FakeClock())

    # WHEN the handle cap is exceeded
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.players"):
        for index in range(65):
            reporter.observe(_ADD.format(handle=f"0({index})"))

    # THEN the cap warning is still emitted and no roster line is emitted
    assert "handle cap" in caplog.text
    assert "Player joined" not in caplog.text


def test_summary_expires_unnamed_handle_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an unnamed handle added at time zero
    clock = _FakeClock()
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_poll_interval=60), clock=clock)
    reporter.observe(_ADD.format(handle="0(0)"))

    # WHEN the summary runs after the grace period
    clock.now = 300.0
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        reporter.log_summary()

    # THEN the expiry warning is logged, no leave line is logged, and the summary is empty
    assert "expired after 300s" in caplog.text
    assert "Player left" not in caplog.text
    assert "Players online: 0" in caplog.text
    assert tracker.snapshot().players == ()


def test_observe_and_summary_are_serialized() -> None:
    # GIVEN a reporter with observation blocked inside the tracker
    blocker = _BlockingTracker()
    reporter = PlayerReporter(cast("PresenceTracker", blocker), _settings(player_log=True, player_poll_interval=60))
    observe_thread = threading.Thread(target=lambda: reporter.observe("line"))
    observe_thread.start()
    assert blocker.observe_entered.wait(timeout=1)

    # WHEN a summary is requested from another thread
    summary_started = threading.Event()

    def _summary() -> None:
        summary_started.set()
        reporter.log_summary()

    summary_thread = threading.Thread(target=_summary)
    summary_thread.start()
    assert summary_started.wait(timeout=1)

    # THEN the summary waits for the observation and emission to finish
    assert not blocker.expired.is_set()
    blocker.release_observe.set()
    observe_thread.join(timeout=1)
    summary_thread.join(timeout=1)
    assert blocker.expired.is_set()


def test_start_returns_none_when_output_or_interval_is_disabled() -> None:
    # GIVEN output disabled and a separate zero-interval tracker
    tracker = PresenceTracker()
    stop = threading.Event()

    # WHEN starting each reporter
    disabled = PlayerReporter(tracker, _settings(player_log=False, player_poll_interval=60))
    zero_interval = PlayerReporter(tracker, _settings(player_log=True, player_poll_interval=0))

    # THEN neither starts a thread
    assert disabled.start(stop) is None
    assert zero_interval.start(stop) is None


def test_start_returns_running_thread_when_enabled() -> None:
    # GIVEN roster output and a summary interval
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_log=True, player_poll_interval=60))
    stop = threading.Event()

    # WHEN the reporter starts
    thread = reporter.start(stop)
    assert thread is not None

    # THEN it stops when the lifecycle stop event is set
    stop.set()
    thread.join(timeout=1)
    assert thread.is_alive() is False


def test_summary_thread_logs_once_per_interval(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a reporter with a one-second interval and a stop event that advances deterministically
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_log=True, player_poll_interval=1), clock=_FakeClock())
    stop = _FakeStopEvent()

    # WHEN the summary thread runs
    with caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        thread = reporter.start(cast("threading.Event", stop))
        assert thread is not None
        thread.join(timeout=1)

    # THEN one summary is logged for the interval and the thread exits
    assert thread.is_alive() is False
    assert caplog.text.count("Players online: 0") == 1


def test_large_interval_does_not_overflow_the_wait() -> None:
    # GIVEN an extremely large summary interval
    tracker = PresenceTracker()
    reporter = PlayerReporter(tracker, _settings(player_log=True, player_poll_interval=10**400))
    stop = threading.Event()

    # WHEN the reporter starts and stops
    thread = reporter.start(stop)
    assert thread is not None
    stop.set()
    thread.join(timeout=1)

    # THEN the thread exits without a timeout overflow
    assert thread.is_alive() is False
