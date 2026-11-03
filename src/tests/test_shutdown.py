"""Tests for scheduled backups and the parent-side backup spawner."""

import threading
from unittest.mock import MagicMock, patch

from enshctl.backup.category import Category
from enshctl.backup_protocol import BackupRequest, Trigger
from enshctl.lifecycle import backup as lifecycle_backup


def test_scheduler_runs_scheduled_trigger_and_stops() -> None:
    # GIVEN a scheduler whose first backup stops the loop
    stop = threading.Event()
    calls: list[BackupRequest] = []

    def _record(request: BackupRequest | None = None) -> None:
        calls.append(request or BackupRequest())
        stop.set()

    # WHEN the scheduler runs
    with patch.object(lifecycle_backup, "run_backup", side_effect=_record):
        thread = lifecycle_backup.start_scheduler("*/60 * * * *", stop)
        thread.join(timeout=1)

    # THEN the immediate backup uses the scheduled trigger and the loop exits
    assert calls == [BackupRequest.for_trigger(Trigger.SCHEDULED)]


def test_scheduler_skips_immediate_backup_when_stopped() -> None:
    # GIVEN a scheduler whose stop event is already set
    stop = threading.Event()
    stop.set()

    # WHEN the scheduler starts
    with patch.object(lifecycle_backup, "run_backup") as mock_run:
        thread = lifecycle_backup.start_scheduler("*/60 * * * *", stop)
        thread.join(timeout=1)

    # THEN no backup runs after shutdown began
    mock_run.assert_not_called()


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
