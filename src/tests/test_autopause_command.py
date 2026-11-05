"""Tests for the Auto Pause CLI."""

import os
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from enshctl.commands import autopause
from enshctl.lifecycle.control import AutoPauseStatus, ControlFiles
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _live(control: ControlFiles, **overrides: object) -> None:
    status = AutoPauseStatus(
        state="active",
        players=(),
        updated_at=time.time(),
        controller_pid=os.getpid(),
    )
    control.write_status(replace(status, **overrides))  # type: ignore[arg-type]


def _patch_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(autopause, "AUTOPAUSE_DIR", tmp_path)


def test_status_reports_stale_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN no status file
    _patch_dir(monkeypatch, tmp_path)

    # WHEN status runs
    code = autopause.run(AppSettings(), ["status"])

    # THEN the unavailable code is returned
    assert code == 3


def test_status_reports_live_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # GIVEN a fresh live status
    _patch_dir(monkeypatch, tmp_path)
    _live(ControlFiles(root=tmp_path, puid=0, pgid=0), players=("Alice",), session_veto=True)

    # WHEN status runs
    code = autopause.run(AppSettings(), ["status"])

    # THEN the state is printed
    assert code == 0
    assert "Auto Pause: active" in capsys.readouterr().out


def test_pause_request_reports_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN a live controller and a request consumer that writes a pending result
    _patch_dir(monkeypatch, tmp_path)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    _live(control)
    original = ControlFiles.write_request

    def _write(self: ControlFiles, action: str, token: str, *, now: float | None = None) -> object:
        request = original(self, action, token, now=now)
        status = self.read_status()
        assert status is not None
        self.write_status(replace(status, last_request=token, last_result="pending", updated_at=time.time()))
        return request

    monkeypatch.setattr(ControlFiles, "write_request", _write)

    # WHEN pause runs
    code = autopause.run(AppSettings(), ["pause"])

    # THEN the accepted request exits cleanly
    assert code == 0


def test_pause_request_reports_refusal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN a live controller and a request consumer that records a refusal
    _patch_dir(monkeypatch, tmp_path)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    _live(control)
    original = ControlFiles.write_request

    def _write(self: ControlFiles, action: str, token: str, *, now: float | None = None) -> object:
        request = original(self, action, token, now=now)
        status = self.read_status()
        assert status is not None
        self.write_status(replace(status, last_request=token, last_result="refused", updated_at=time.time()))
        return request

    monkeypatch.setattr(ControlFiles, "write_request", _write)

    # WHEN pause runs
    code = autopause.run(AppSettings(), ["pause"])

    # THEN the refusal code is returned
    assert code == 2


def test_request_timeout_returns_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN a live controller that never reports the token
    _patch_dir(monkeypatch, tmp_path)
    _live(ControlFiles(root=tmp_path, puid=0, pgid=0))
    monkeypatch.setattr(autopause, "REQUEST_TIMEOUT", 0.01)
    monkeypatch.setattr(autopause, "REQUEST_POLL_INTERVAL", 0.001)

    # WHEN pause runs
    code = autopause.run(AppSettings(), ["pause"])

    # THEN the timeout code is returned
    assert code == 3


def test_reset_with_players_refuses_without_yes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN a live controller with a player online
    _patch_dir(monkeypatch, tmp_path)
    _live(ControlFiles(root=tmp_path, puid=0, pgid=0), players=("Alice",))

    # WHEN reset runs without --yes
    code = autopause.run(AppSettings(), ["reset"])

    # THEN it refuses before writing a request
    assert code == 2


def test_reset_yes_sends_force_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN a live controller with a player online
    _patch_dir(monkeypatch, tmp_path)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    _live(control, players=("Alice",))
    actions: list[str] = []
    original = ControlFiles.write_request

    def _write(self: ControlFiles, action: str, token: str, *, now: float | None = None) -> object:
        actions.append(action)
        request = original(self, action, token, now=now)
        status = self.read_status()
        assert status is not None
        self.write_status(replace(status, last_request=token, last_result="applied", updated_at=time.time()))
        return request

    monkeypatch.setattr(ControlFiles, "write_request", _write)

    # WHEN reset runs with --yes
    code = autopause.run(AppSettings(), ["reset", "--yes"])

    # THEN the force action is sent
    assert code == 0
    assert actions == ["reset-force"]


def test_enable_reports_marker_removal_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN a disabled marker that cannot be removed
    _patch_dir(monkeypatch, tmp_path)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)
    control.set_disabled()
    monkeypatch.setattr(ControlFiles, "clear_disabled", lambda _self: False)

    # WHEN enable runs
    code = autopause.run(AppSettings(), ["enable"])

    # THEN the failure is reported
    assert code == 1


def test_disable_and_enable_work_without_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # GIVEN no live controller
    _patch_dir(monkeypatch, tmp_path)
    control = ControlFiles(root=tmp_path, puid=0, pgid=0)

    # WHEN disable and enable run
    assert autopause.run(AppSettings(), ["disable"]) == 0
    assert control.is_disabled() is True
    assert autopause.run(AppSettings(), ["enable"]) == 0
    assert control.is_disabled() is False
