"""Tests for the Auto Pause quiet-window gate."""

import threading

from enshctl.lifecycle.pause_gate import PauseGate


def test_quiet_window_waits_for_admitted_work() -> None:
    # GIVEN a running gate with admitted work
    gate = PauseGate()
    stop = threading.Event()
    assert gate.acquire(stop) is True
    assert gate.acquire(stop) is True

    # WHEN a quiet window is requested while the work is in flight
    # THEN it is refused and more work is still admitted
    assert gate.try_quiet() is False
    assert gate.is_quiet is False
    assert gate.acquire(stop) is True

    # WHEN the work finishes and a quiet window starts
    gate.release()
    gate.release()
    gate.release()
    assert gate.try_quiet() is True

    # THEN new work is refused until the window resumes
    assert gate.acquire(stop) is False
    gate.resume()
    assert gate.acquire(stop) is True
    gate.release()


def test_wait_until_running_returns_after_resume() -> None:
    # GIVEN a held quiet window
    gate = PauseGate()
    stop = threading.Event()
    assert gate.try_quiet() is True
    result: list[bool] = []

    # WHEN a worker waits for the window to end and the window resumes
    thread = threading.Thread(target=lambda: result.append(gate.wait_until_running(stop)))
    thread.start()
    gate.resume()
    thread.join(timeout=1)

    # THEN the wait succeeds
    assert result == [True]
    assert gate.is_quiet is False


def test_wait_until_running_stops_without_resume() -> None:
    # GIVEN a held quiet window and a stop request
    gate = PauseGate()
    stop = threading.Event()
    stop.set()
    assert gate.try_quiet() is True

    # WHEN a worker waits while stopping
    # THEN the wait reports failure without requiring a resume
    assert gate.wait_until_running(stop) is False


def test_wait_until_running_stops_even_after_resume() -> None:
    # GIVEN a held quiet window and a stop request
    gate = PauseGate()
    stop = threading.Event()
    stop.set()
    assert gate.try_quiet() is True

    # WHEN the window is resumed during shutdown
    gate.resume()

    # THEN the wait still reports failure
    assert gate.wait_until_running(stop) is False


def test_acquire_refuses_when_stopping() -> None:
    # GIVEN a stop request
    gate = PauseGate()
    stop = threading.Event()
    stop.set()

    # WHEN work is admitted
    # THEN it is refused
    assert gate.acquire(stop) is False
