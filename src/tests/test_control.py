"""Tests for Auto Pause control files."""

from dataclasses import replace
from typing import TYPE_CHECKING

from enshctl.lifecycle.control import (
    REQUEST_TTL,
    STATUS_FRESHNESS,
    AutoPauseStatus,
    ControlFiles,
)

if TYPE_CHECKING:
    from pathlib import Path


def _status(**overrides: object) -> AutoPauseStatus:
    base = AutoPauseStatus(
        state="active",
        players=("Alice",),
        pending_join=False,
        session_veto=True,
        degraded=False,
        paused_since=None,
        last_error=None,
        wake_filter="any",
        a2s="ok",
        last_request="token",
        last_result="pending",
        updated_at=100.0,
        controller_pid=42,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_status_round_trips(tmp_path: Path) -> None:
    # GIVEN a control directory and a status value
    control = ControlFiles(root=tmp_path)
    status = _status()

    # WHEN the status is written and read
    control.write_status(status)

    # THEN the whole value round-trips
    assert control.read_status() == status


def test_live_status_requires_fresh_timestamp_and_pid(tmp_path: Path) -> None:
    # GIVEN a fresh status
    control = ControlFiles(root=tmp_path)
    status = _status(updated_at=100.0, controller_pid=42)
    control.write_status(status)

    # WHEN the timestamp and PID are valid
    live = control.live_status(now=100.0 + STATUS_FRESHNESS - 1, pid_alive=lambda pid: pid == 42)

    # THEN it is live
    assert live == status

    # AND a stale timestamp is rejected
    assert control.live_status(now=100.0 + STATUS_FRESHNESS + 1, pid_alive=lambda _pid: True) is None

    # AND a dead PID is rejected
    assert control.live_status(now=100.0, pid_alive=lambda _pid: False) is None


def test_request_round_trips_and_deletes(tmp_path: Path) -> None:
    # GIVEN a control directory
    control = ControlFiles(root=tmp_path)

    # WHEN a request is written and consumed
    request = control.write_request("pause", "token-1", now=10.0)
    consumed = control.consume_request(now=10.0)

    # THEN the token and action round-trip and the file is deleted
    assert consumed == request
    assert control.request_path.exists() is False


def test_expired_request_is_ignored(tmp_path: Path) -> None:
    # GIVEN an expired request
    control = ControlFiles(root=tmp_path)
    control.write_request("resume", "token-2", now=10.0)

    # WHEN it is consumed after its lifetime
    consumed = control.consume_request(now=10.0 + REQUEST_TTL + 1)

    # THEN it is ignored and removed
    assert consumed is None
    assert control.request_path.exists() is False


def test_clear_runtime_preserves_disabled(tmp_path: Path) -> None:
    # GIVEN disabled, paused, status, and request state
    control = ControlFiles(root=tmp_path)
    control.set_disabled()
    control.set_paused()
    control.write_status(_status())
    control.write_request("reset", "token-3", now=10.0)

    # WHEN transient state is cleared
    control.clear_runtime()

    # THEN only the disabled marker survives
    assert control.is_disabled() is True
    assert control.is_paused() is False
    assert control.status_path.exists() is False
    assert control.request_path.exists() is False
