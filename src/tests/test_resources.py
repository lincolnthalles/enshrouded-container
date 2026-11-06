"""Tests for resource polling and its Auto Pause quiet window."""

import threading
from typing import TYPE_CHECKING, cast, override
from unittest.mock import patch

from enshctl import resources
from enshctl.lifecycle.pause_gate import PauseGate

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


class _StopAfter:
    def __init__(self, waits: int, on_wait: Callable[[int], None] | None = None) -> None:
        self._remaining = waits
        self._on_wait = on_wait

    def is_set(self) -> bool:
        return self._remaining <= 0

    def wait(self, timeout: float) -> bool:
        del timeout
        if self._on_wait is not None:
            self._on_wait(self._remaining)
        self._remaining -= 1
        return self._remaining <= 0


class _ObservedGate(PauseGate):
    def __init__(self) -> None:
        super().__init__()
        self.waiting = threading.Event()

    @override
    def wait_until_running(self, stop_event: threading.Event) -> bool:
        self.waiting.set()
        return super().wait_until_running(stop_event)


def test_resource_poller_logs_usage_once_per_interval(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an enabled poller with deterministic process data
    stop = _StopAfter(2)
    gate = PauseGate()

    # WHEN the poller runs for one interval
    with (
        patch.object(resources, "read_pid_cpu_ticks", return_value=100),
        patch.object(resources, "read_pid_rss", return_value=10),
        patch.object(resources, "read_system_cpu_ticks", return_value=1000),
        patch.object(resources, "get_all_child_pids", return_value=[]),
        caplog.at_level("INFO", logger="enshctl.resources"),
    ):
        thread = resources.start_resource_poller(
            1,
            cast("threading.Event", stop),
            pause_gate=gate,
            interval=1,
        )
        assert thread is not None
        thread.join(timeout=1)

    # THEN one resource-usage line is logged and the poller exits
    assert thread.is_alive() is False
    assert caplog.text.count("enshrouded_server.exe:") == 1


def test_resource_poller_suspends_and_resumes_with_quiet_window(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a poller that samples once and then meets a held quiet window
    gate = _ObservedGate()

    def _hold_quiet(remaining: int) -> None:
        if remaining == 3:
            assert gate.try_quiet() is True

    stop = _StopAfter(4, on_wait=_hold_quiet)

    # WHEN the quiet window ends and one full interval elapses
    with (
        patch.object(resources, "read_pid_cpu_ticks", return_value=100) as cpu_ticks,
        patch.object(resources, "read_pid_rss", return_value=10),
        patch.object(resources, "read_system_cpu_ticks", return_value=1000),
        patch.object(resources, "get_all_child_pids", return_value=[]),
        caplog.at_level("INFO", logger="enshctl.resources"),
    ):
        thread = resources.start_resource_poller(
            1,
            cast("threading.Event", stop),
            pause_gate=gate,
            interval=1,
        )
        assert thread is not None
        assert gate.waiting.wait(timeout=1)
        reads_before_resume = cpu_ticks.call_count
        assert reads_before_resume == 4
        gate.resume()
        thread.join(timeout=1)

    # THEN no sample is read while quiet and both usage lines surround the transition
    text = caplog.text
    first_usage = text.index("enshrouded_server.exe:")
    second_usage = text.index("enshrouded_server.exe:", first_usage + 1)
    assert thread.is_alive() is False
    assert first_usage < text.index("Resource polling suspended by Auto Pause") < text.index("Resource polling resumed")
    assert text.index("Resource polling resumed") < second_usage
    assert cpu_ticks.call_count > reads_before_resume


def test_resource_poller_reads_no_baseline_while_quiet(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a poller started while the quiet window is already held
    gate = _ObservedGate()
    assert gate.try_quiet() is True
    stop = _StopAfter(2)

    # WHEN the poller starts and the window ends
    with (
        patch.object(resources, "read_pid_cpu_ticks", return_value=100) as cpu_ticks,
        patch.object(resources, "read_pid_rss", return_value=10),
        patch.object(resources, "read_system_cpu_ticks", return_value=1000),
        patch.object(resources, "get_all_child_pids", return_value=[]),
        caplog.at_level("INFO", logger="enshctl.resources"),
    ):
        thread = resources.start_resource_poller(
            1,
            cast("threading.Event", stop),
            pause_gate=gate,
            interval=1,
        )
        assert thread is not None
        assert gate.waiting.wait(timeout=1)
        assert cpu_ticks.call_count == 0
        gate.resume()
        thread.join(timeout=1)

    # THEN no baseline read happened while quiet and polling resumes afterwards
    assert thread.is_alive() is False
    assert cpu_ticks.call_count > 0


def test_resource_poller_disabled_returns_none() -> None:
    # GIVEN a non-positive interval
    # WHEN the poller starts
    thread = resources.start_resource_poller(1, threading.Event(), pause_gate=PauseGate(), interval=0)

    # THEN no thread is created
    assert thread is None
