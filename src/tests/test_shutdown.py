"""Tests for graceful shutdown ordering and backup detachment."""

import subprocess
import threading
from argparse import Namespace
from dataclasses import replace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from enshctl.backup.category import Category
from enshctl.backup_protocol import BackupRequest
from enshctl.commands.start import ServerContext, _make_sigterm_handler, _scheduler_loop
from enshctl.settings import AppSettings


def _settings(**kwargs: object) -> AppSettings:
    return replace(AppSettings(), **cast("dict[str, Any]", kwargs))


def test_shutdown_orders_sigint_before_cold_before_wineserver() -> None:
    import enshctl.commands.start as st

    # GIVEN a running server process and saves present
    ctx = ServerContext()
    proc = MagicMock()
    proc.poll.return_value = None
    ctx.server_process = proc
    order: list[str] = []

    def fake_signal(sig: object) -> None:
        order.append("sigint")

    proc.send_signal.side_effect = fake_signal
    settings = _settings(shutdown_timeout=60, shutdown_backup_wait=5)

    def record_cold(*args: object, **kwargs: object) -> None:
        order.append("cold")

    with (
        patch.object(st.backup, "backup_needed", return_value=True),
        patch.object(st, "_run_backup", side_effect=record_cold) as mock_backup,
        patch.object(st, "_cleanup_wineserver", side_effect=lambda _s: order.append("wine")),
        patch("pathlib.Path.unlink"),
    ):
        # WHEN SIGTERM is handled
        handler = _make_sigterm_handler(ctx, settings, threading.Event())
        with pytest.raises(SystemExit):
            handler(15, None)
    # THEN SIGINT precedes the cold backup, which precedes Wine cleanup
    assert order == ["sigint", "cold", "wine"]
    # AND the cold backup waits on the lock with the configured bound
    from enshctl.backup_protocol import BackupRequest

    mock_backup.assert_called_once_with(
        BackupRequest(category=Category.COLD, wait_seconds=5, detach=True),
    )


def test_shutdown_sigkills_stubborn_server_after_grace() -> None:
    import enshctl.commands.start as st

    # GIVEN a server that ignores SIGINT past the grace period
    ctx = ServerContext()
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 1), 0]
    ctx.server_process = proc
    settings = _settings(shutdown_timeout=1, shutdown_backup_wait=0, backup_cold=False)

    with (
        patch.object(st, "_cleanup_wineserver"),
        patch("pathlib.Path.unlink"),
    ):
        # WHEN SIGTERM is handled
        handler = _make_sigterm_handler(ctx, settings, threading.Event())
        with pytest.raises(SystemExit):
            handler(15, None)
    # THEN the process is killed after the grace expires
    proc.kill.assert_called_once()


def test_cold_and_emergency_backups_detached() -> None:
    import enshctl.commands.start as st

    # GIVEN shutdown and emergency paths without ambient settings
    with patch.object(st, "environ", {"PATH": "/usr/bin"}):
        with patch.object(st.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            # WHEN a detached cold backup runs
            st._run_backup(BackupRequest(category=Category.COLD, detach=True))
            # THEN it survives the parent's process group
            assert mock_run.call_args.kwargs["start_new_session"] is True

        with patch.object(st.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            # WHEN a non-detached scheduled backup runs
            st._run_backup()
            # THEN it stays in the parent's process group
            assert mock_run.call_args.kwargs["start_new_session"] is False

        with patch.object(st.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            # WHEN a detached emergency backup runs
            st._run_backup(BackupRequest(category=Category.EMERGENCY, detach=True))
            # THEN it survives the parent's process group
            assert mock_run.call_args.kwargs["start_new_session"] is True


@pytest.mark.parametrize(
    ("category", "flag"),
    [
        (Category.LIVE, []),
        (Category.COLD, ["--cold"]),
        (Category.EMERGENCY, ["--emergency"]),
    ],
)
def test_backup_request_argv_round_trip(category: Category, flag: list[str]) -> None:
    # GIVEN a typed Backup request
    request = BackupRequest(category=category, wait_seconds=7)
    # WHEN it crosses the child-process seam
    assert request.to_argv() == [*flag, "--wait", "7"]
    args = Namespace(cold=category is Category.COLD, emergency=category is Category.EMERGENCY, wait=7)
    # THEN the child reconstructs the same request
    assert BackupRequest.from_argv(args) == request


def test_backup_request_rejects_unknown_category() -> None:
    # GIVEN an unknown Category string at the protocol boundary
    # WHEN constructing a request
    # THEN it fails before reaching argv
    with pytest.raises(ValueError, match="warm"):
        BackupRequest(category=cast("Category", "warm"))


def test_wait_expiry_warns() -> None:
    import enshctl.backup_runner as br
    from enshctl.backup_protocol import BackupOutcome

    # GIVEN a lock held past the wait bound
    with (
        patch.object(br, "load_settings", return_value=AppSettings()),
        patch.object(br, "acquire_lock", return_value=None),
        patch("sys.argv", ["prog", "--wait", "1"]),
        patch.object(br.time, "monotonic", side_effect=[0.0, 0.0, 2.0]),
    ):
        # WHEN the runner gives up waiting
        code = br.main()
    # THEN it exits lock-held (skip is reported via warning log)
    assert code == BackupOutcome.LOCK_HELD


def test_run_backup_forwards_settings_env() -> None:
    import enshctl.commands.start as st

    # GIVEN settings-bearing env vars set in the parent
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
        "UNRELATED_SECRET": "nope",
    }
    with patch.object(st.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        # WHEN a backup subprocess is spawned
        with patch.object(st, "environ", source):
            st._run_backup()
        # THEN the declared settings keys cross the seam but unknown and unrelated vars do not
        env = mock_run.call_args.kwargs["env"]
        assert env["BACKUP_DIR"] == "/mnt/nfs/backups"
        assert env["BACKUP_KEEP_LAST"] == "7"
        assert env["PUID"] == "1001"
        assert env["PGID"] == "1002"
        assert env["ORCHESTRATOR_LOG_FILE"] == ""
        assert "BACKUP_FUTURE_UNKNOWN" not in env
        assert "PERSIST_FILES" not in env
        assert "WINEARCH" not in env
        assert "UNRELATED_SECRET" not in env
        assert "STEAM_PASSWORD" not in env


def test_signal_game_uses_pkill() -> None:
    import signal as sigmod

    import enshctl.commands.start as st

    # GIVEN a running game server
    with patch.object(st.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # WHEN signaling the game
        delivered = st._signal_game(sigmod.SIGINT)
    # THEN pkill targets the game binary as steam
    assert delivered is True
    cmd = mock_run.call_args.args[0]
    assert cmd[:4] == ["/usr/bin/runuser", "-u", "steam", "--"]
    assert "enshrouded_server.exe" in cmd


def test_second_signal_is_ignored() -> None:
    import enshctl.commands.start as st

    # GIVEN a shutdown already in progress
    ctx = ServerContext()
    ctx.shutdown_requested = True
    settings = _settings()

    with patch.object(st, "_cleanup_wineserver") as mock_cleanup:
        # WHEN a second signal arrives
        handler = _make_sigterm_handler(ctx, settings, threading.Event())
        result = handler(15, None)
    # THEN the handler returns without doing anything
    assert result is None
    mock_cleanup.assert_not_called()


def test_scheduler_stops_on_event() -> None:
    import enshctl.commands.start as st

    # GIVEN an already-set stop event
    stop = threading.Event()
    stop.set()
    with patch.object(st, "_run_backup") as mock_backup:
        # WHEN the scheduler loop starts
        _scheduler_loop("*/60 * * * *", stop)
    # THEN only the immediate backup runs and the loop exits
    mock_backup.assert_called_once_with()
