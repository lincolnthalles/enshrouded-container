"""Tests for scheduled backups and the parent-side backup spawner."""

import threading
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from enshctl.backup.category import Category
from enshctl.backup_protocol import BackupRequest, Trigger
from enshctl.lifecycle import backup as lifecycle_backup
from enshctl.lifecycle.pause_gate import PauseGate

if TYPE_CHECKING:
    from pathlib import Path


class _StopAfterFirstWait:
    def __init__(self) -> None:
        self._waits = 0

    def is_set(self) -> bool:
        return self._waits >= 1

    def wait(self, timeout: float) -> bool:
        del timeout
        self._waits += 1
        return True


class _ResumeGateOnWait:
    def __init__(self, gate: PauseGate) -> None:
        self._gate = gate
        self._waits = 0

    def is_set(self) -> bool:
        return self._waits >= 2

    def wait(self, timeout: float) -> bool:
        del timeout
        self._waits += 1
        if self._waits == 1:
            self._gate.resume()
            return False
        return True


def test_scheduler_runs_scheduled_trigger_and_stops() -> None:
    # GIVEN a scheduler whose first backup stops the loop
    stop = threading.Event()
    calls: list[BackupRequest] = []

    def _record(request: BackupRequest | None = None, *, saves_dir: Path | None = None) -> None:
        del saves_dir
        calls.append(request or BackupRequest())
        stop.set()

    # WHEN the scheduler runs
    with patch.object(lifecycle_backup, "run_backup", side_effect=_record):
        thread = lifecycle_backup.start_scheduler("*/60 * * * *", stop, pause_gate=PauseGate())
        thread.join(timeout=1)

    # THEN the immediate backup uses the scheduled trigger and the loop exits
    assert calls == [BackupRequest.for_trigger(Trigger.SCHEDULED)]


def test_scheduler_skips_immediate_backup_when_stopped() -> None:
    # GIVEN a scheduler whose stop event is already set
    stop = threading.Event()
    stop.set()

    # WHEN the scheduler starts
    with patch.object(lifecycle_backup, "run_backup") as mock_run:
        thread = lifecycle_backup.start_scheduler("*/60 * * * *", stop, pause_gate=PauseGate())
        thread.join(timeout=1)

    # THEN no backup runs after shutdown began
    mock_run.assert_not_called()


def test_scheduler_skips_backup_while_quiet_window_is_held() -> None:
    # GIVEN a held Auto Pause quiet window
    stop = _StopAfterFirstWait()
    gate = PauseGate()
    assert gate.try_quiet() is True
    calls: list[BackupRequest] = []

    def _record(request: BackupRequest | None = None, *, saves_dir: Path | None = None) -> None:
        del saves_dir
        calls.append(request or BackupRequest())

    # WHEN the scheduler runs a tick
    with patch.object(lifecycle_backup, "run_backup", side_effect=_record):
        thread = lifecycle_backup.start_scheduler(
            "*/60 * * * *",
            cast("threading.Event", stop),
            pause_gate=gate,
        )
        thread.join(timeout=1)

    # THEN no backup runs and the scheduler thread exits
    assert calls == []
    assert thread.is_alive() is False


def test_scheduler_forwards_resolved_save_dir(tmp_path: Path) -> None:
    # GIVEN a scheduler bound to the parent's resolved Save directory
    gate = PauseGate()
    stop = _StopAfterFirstWait()
    received: list[Path | None] = []

    def _record(_request: BackupRequest | None = None, *, saves_dir: Path | None = None) -> None:
        received.append(saves_dir)

    # WHEN the scheduler runs a tick
    with patch.object(lifecycle_backup, "run_backup", side_effect=_record):
        thread = lifecycle_backup.start_scheduler(
            "*/60 * * * *",
            cast("threading.Event", stop),
            pause_gate=gate,
            saves_dir=tmp_path,
        )
        thread.join(timeout=1)

    # THEN the resolved Save directory crosses to the backup subprocess request
    assert received == [tmp_path]
    assert thread.is_alive() is False


def test_scheduler_runs_next_tick_after_quiet_window_ends() -> None:
    # GIVEN a held quiet window that ends before the next scheduled tick
    gate = PauseGate()
    assert gate.try_quiet() is True
    stop = _ResumeGateOnWait(gate)
    calls: list[BackupRequest] = []

    def _record(request: BackupRequest | None = None, *, saves_dir: Path | None = None) -> None:
        del saves_dir
        calls.append(request or BackupRequest())

    # WHEN the scheduler runs past the quiet window
    with patch.object(lifecycle_backup, "run_backup", side_effect=_record):
        thread = lifecycle_backup.start_scheduler(
            "*/60 * * * *",
            cast("threading.Event", stop),
            pause_gate=gate,
        )
        thread.join(timeout=1)

    # THEN only the post-window tick runs, with no catch-up for the skipped tick
    assert calls == [BackupRequest.for_trigger(Trigger.SCHEDULED)]
    assert thread.is_alive() is False


def test_run_backup_forwards_settings_env() -> None:
    # GIVEN settings-bearing env vars in the parent environment
    source = {
        "PATH": "/usr/bin",
        "BACKUP_DIR": "/mnt/nfs/backups",
        "BACKUP_KEEP_LAST": "7",
        "PUID": "1001",
        "PGID": "1002",
        "BACKUP_FUTURE_UNKNOWN": "nope",
        "PERSIST_FILES": "world.db",
        "WINEARCH": "win64",
        "STEAM_PASSWORD": "s3cret",
        "ORCHESTRATOR_LOG_FILE": "yes",
        "UNRELATED_SECRET": "nope",
    }
    with patch.object(lifecycle_backup.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        # WHEN a backup subprocess is spawned
        lifecycle_backup.run_backup(env=source)

    # THEN declared settings keys cross the seam but unknown and unrelated vars do not
    env = mock_run.call_args.kwargs["env"]
    assert env["BACKUP_DIR"] == "/mnt/nfs/backups"
    assert env["BACKUP_KEEP_LAST"] == "7"
    assert env["PUID"] == "1001"
    assert env["PGID"] == "1002"
    assert "ORCHESTRATOR_LOG_FILE" not in env
    assert "BACKUP_FUTURE_UNKNOWN" not in env
    assert "PERSIST_FILES" not in env
    assert "WINEARCH" not in env
    assert "UNRELATED_SECRET" not in env
    assert "STEAM_PASSWORD" not in env


def test_run_backup_includes_resolved_save_dir(tmp_path: Path) -> None:
    # GIVEN a resolved Save directory
    with patch.object(lifecycle_backup.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")

        # WHEN a backup subprocess is spawned
        lifecycle_backup.run_backup(saves_dir=tmp_path, env={})

    # THEN the child receives the Save directory on its argv
    assert mock_run.call_args.args[0] == ["enshctl", "backup", "--saves-dir", str(tmp_path)]


def test_detached_requests_survive_process_group() -> None:
    # GIVEN requests with different detachment policy
    with patch.object(lifecycle_backup.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        # WHEN a detached cold backup runs
        lifecycle_backup.run_backup(
            BackupRequest(category=Category.COLD, detach=True),
            env={"PATH": "/usr/bin"},
        )
        # THEN it survives the parent's process group
        assert mock_run.call_args.kwargs["start_new_session"] is True

        # WHEN a non-detached scheduled backup runs
        lifecycle_backup.run_backup(env={"PATH": "/usr/bin"})
        # THEN it stays in the parent's process group
        assert mock_run.call_args.kwargs["start_new_session"] is False
