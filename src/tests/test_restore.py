"""Tests for restore command."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from enshctl.backup.catalog import BackupInfo, BackupName
from enshctl.commands.restore import RestoreSeams, confirm_restore
from enshctl.config import SaveDirectories
from enshctl.disk_space import SpaceGuard
from enshctl.pidfile import PidFile
from enshctl.restore import RestoreError
from enshctl.settings import AppSettings


def _backup_file(tmp_path: Path) -> Path:
    backup = tmp_path / "backups" / "enshrouded-20260529-120000.tar.zst"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"backup")
    return backup


def _backup_info(backup: Path) -> BackupInfo:
    name = BackupName.from_filename(backup.name)
    assert name is not None
    return BackupInfo(path=backup, name=name, size=backup.stat().st_size)


class FakeLock:
    def __init__(self, fd: int | None = 3) -> None:
        self._fd = fd
        self.acquired: list[tuple[Path, int]] = []
        self.released: list[int] = []

    def acquire(self, path: Path, wait_seconds: int = 0) -> int | None:
        self.acquired.append((path, wait_seconds))
        return self._fd

    def release(self, fd: int) -> None:
        self.released.append(fd)


def test_confirm_restore_rich_yes() -> None:
    mock_confirm = MagicMock()
    mock_confirm.Confirm.ask.return_value = True
    mock_rich_console = MagicMock()
    modules = {"rich": MagicMock(), "rich.console": mock_rich_console, "rich.prompt": mock_confirm}
    with patch.dict("sys.modules", modules), patch("builtins.input"):
        assert confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is True


def test_confirm_restore_rich_no() -> None:
    mock_confirm = MagicMock()
    mock_confirm.Confirm.ask.return_value = False
    mock_rich_console = MagicMock()
    modules = {"rich": MagicMock(), "rich.console": mock_rich_console, "rich.prompt": mock_confirm}
    with patch.dict("sys.modules", modules), patch("builtins.input"):
        assert confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is False


def test_confirm_restore_fallback_input_yes() -> None:
    with patch("builtins.input", return_value="y"), patch.dict("sys.modules", {"rich": None}):
        assert confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is True


def test_confirm_restore_fallback_input_no() -> None:
    with patch("builtins.input", return_value="n"), patch.dict("sys.modules", {"rich": None}):
        assert confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is False


def test_restore_command_uses_configured_saves(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup and an absolute configured saves directory
    backup = _backup_file(tmp_path)
    saves = tmp_path / "custom" / "saves"
    marker = tmp_path / "enshctl.pid"
    lock = FakeLock()
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(saves)),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running the restore command
        result = cmd.run(AppSettings(), ["--file", backup.name, "--yes"], seams=RestoreSeams(lock=lock))

    # THEN the restore targets the configured saves directory and a sibling temp directory
    # AND the acquired lock is released
    assert result == 0
    assert lock.released == [3]
    assert mock_restore.call_args.args[0] == backup
    kwargs = mock_restore.call_args.kwargs
    assert kwargs["saves_dir"] == saves
    assert kwargs["tmp_dir"] == saves.parent / "saves-restore-tmp"
    assert kwargs["space"] == SpaceGuard()


def test_restore_command_reports_lock_held(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup while another backup operation holds the lock
    backup = _backup_file(tmp_path)
    saves = tmp_path / "saves"
    marker = tmp_path / "enshctl.pid"
    lock = FakeLock(fd=None)
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(saves)),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running the restore command
        result = cmd.run(AppSettings(), ["--file", backup.name, "--yes"], seams=RestoreSeams(lock=lock))

    # THEN it reports the held lock without restoring or releasing another owner's descriptor
    assert result == 1
    assert len(lock.acquired) == 1
    assert lock.acquired[0][1] == 0
    assert lock.released == []
    mock_restore.assert_not_called()


def test_restore_command_releases_lock_when_restore_fails(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup and a restore that fails after the lock is acquired
    backup = _backup_file(tmp_path)
    saves = tmp_path / "saves"
    marker = tmp_path / "enshctl.pid"
    lock = FakeLock()
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(saves)),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup", side_effect=RestoreError),
    ):
        # WHEN running the restore command
        result = cmd.run(AppSettings(), ["--file", backup.name, "--yes"], seams=RestoreSeams(lock=lock))

    # THEN the failure is reported and the acquired lock is released
    assert result == 1
    assert lock.released == [3]


def test_restore_command_refuses_running_server(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup while the server is running
    backup = _backup_file(tmp_path)
    marker = tmp_path / "enshctl.pid"
    marker.touch()
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running the restore command
        result = cmd.run(AppSettings(), ["--file", backup.name, "--yes"])

    # THEN it refuses without touching the saves
    assert result == 1
    mock_restore.assert_not_called()


def test_restore_command_confirms_before_restore(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup and a confirmation that accepts
    backup = _backup_file(tmp_path)
    saves = tmp_path / "custom" / "saves"
    marker = tmp_path / "enshctl.pid"
    confirm = MagicMock(return_value=True)
    lock = FakeLock()
    seams = RestoreSeams(confirm_restore=confirm, select_backup=MagicMock(), lock=lock)
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(saves)),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running without --yes
        result = cmd.run(AppSettings(), ["--file", backup.name], seams=seams)

    # THEN the prompt shows the Backup details and the restore proceeds
    assert result == 0
    confirm.assert_called_once_with(backup.name, backup.stat().st_size, saves)
    mock_restore.assert_called_once()


def test_restore_command_declines_and_cancels(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup and a confirmation that declines
    backup = _backup_file(tmp_path)
    marker = tmp_path / "enshctl.pid"
    confirm = MagicMock(return_value=False)
    lock = FakeLock()
    seams = RestoreSeams(confirm_restore=confirm, select_backup=MagicMock(), lock=lock)
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(tmp_path / "saves")),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN the user declines
        result = cmd.run(AppSettings(), ["--file", backup.name], seams=seams)

    # THEN the command exits zero without locking or restoring
    assert result == 0
    assert lock.acquired == []
    mock_restore.assert_not_called()


def test_restore_command_yes_skips_confirmation(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a confirmation seam that must not run
    backup = _backup_file(tmp_path)
    marker = tmp_path / "enshctl.pid"
    confirm = MagicMock(side_effect=AssertionError("confirmation must be skipped"))
    lock = FakeLock()
    seams = RestoreSeams(confirm_restore=confirm, select_backup=MagicMock(), lock=lock)
    with (
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(tmp_path / "saves")),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running with --yes
        result = cmd.run(AppSettings(), ["--file", backup.name, "--yes"], seams=seams)

    # THEN the restore proceeds without confirmation
    assert result == 0
    confirm.assert_not_called()
    mock_restore.assert_called_once()


def test_restore_interactive_picker_selection(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a TTY and an interactive picker that selects a Backup
    backup = tmp_path / "live" / "enshrouded-20260529-120000.tar.zst"
    backup.parent.mkdir()
    backup.write_bytes(b"backup")
    settings = replace(AppSettings(), backup_dir=str(tmp_path))
    marker = tmp_path / "enshctl.pid"
    select = MagicMock(return_value=_backup_info(backup))
    seams = RestoreSeams(
        confirm_restore=MagicMock(return_value=True),
        select_backup=select,
        lock=FakeLock(),
    )
    with (
        patch.object(cmd.sys, "stdout", SimpleNamespace(isatty=lambda: True)),
        patch.object(cmd, "generated_save_directories", return_value=SaveDirectories(tmp_path / "saves")),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running restore without selection flags
        result = cmd.run(settings, [], seams=seams)

    # THEN the picker receives the scanned Backups and its selection is restored
    assert result == 0
    select.assert_called_once()
    assert [info.path for info in select.call_args.args[0]] == [backup]
    assert mock_restore.call_args.args[0] == backup


def test_restore_interactive_picker_cancel_exits_one(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a TTY and an interactive picker that is dismissed
    settings = replace(AppSettings(), backup_dir=str(tmp_path))
    select = MagicMock(return_value=None)
    seams = RestoreSeams(confirm_restore=MagicMock(), select_backup=select)

    with (
        patch.object(cmd.sys, "stdout", SimpleNamespace(isatty=lambda: True)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running restore without a selection
        result = cmd.run(settings, [], seams=seams)

    # THEN it reports no match without restoring
    assert result == 1
    select.assert_called_once()
    mock_restore.assert_not_called()


def test_restore_list_prints_plain_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a stored Backup and a non-TTY
    live = tmp_path / "live"
    live.mkdir()
    backup = live / "enshrouded-20260529-120000.tar.zst"
    backup.write_bytes(b"\x00" * 100)
    settings = replace(AppSettings(), backup_dir=str(tmp_path))

    # WHEN listing backups
    result = cmd.run(settings, ["--list"])

    # THEN the plain table reports the filename, category, size, and timestamp
    name = BackupName.from_filename(backup.name)
    assert name is not None
    output = capsys.readouterr().out
    assert result == 0
    assert backup.name in output
    assert "live" in output
    assert "100.0 B" in output
    assert name.timestamp.isoformat() in output


def test_restore_without_flags_on_non_tty_lists_backups(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN stored Backups and a non-TTY
    live = tmp_path / "live"
    live.mkdir()
    backup = live / "enshrouded-20260529-120000.tar.zst"
    backup.write_bytes(b"\x00" * 100)
    settings = replace(AppSettings(), backup_dir=str(tmp_path))

    # WHEN running restore without selection flags
    result = cmd.run(settings, [])

    # THEN it falls back to listing the Backups and exits
    output = capsys.readouterr().out
    assert result == 0
    assert backup.name in output


def test_select_backup_requires_textual() -> None:
    from enshctl.commands import restore_tui

    # GIVEN the Textual app module is unavailable
    with patch.dict("sys.modules", {"textual.app": None}), pytest.raises(RestoreError, match="requires Textual"):
        # WHEN opening the interactive picker
        restore_tui.select_backup([])
