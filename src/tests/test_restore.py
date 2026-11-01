"""Tests for restore command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from enshctl.commands.restore import _confirm_restore
from enshctl.disk_space import SpaceGuard
from enshctl.pidfile import PidFile


def test_confirm_restore_rich_yes() -> None:
    mock_confirm = MagicMock()
    mock_confirm.Confirm.ask.return_value = True
    mock_rich_console = MagicMock()
    modules = {"rich": MagicMock(), "rich.console": mock_rich_console, "rich.prompt": mock_confirm}
    with patch.dict("sys.modules", modules), patch("builtins.input"):
        assert _confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is True


def test_confirm_restore_rich_no() -> None:
    mock_confirm = MagicMock()
    mock_confirm.Confirm.ask.return_value = False
    mock_rich_console = MagicMock()
    modules = {"rich": MagicMock(), "rich.console": mock_rich_console, "rich.prompt": mock_confirm}
    with patch.dict("sys.modules", modules), patch("builtins.input"):
        assert _confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is False


def test_confirm_restore_fallback_input_yes() -> None:
    with patch("builtins.input", return_value="y"), patch.dict("sys.modules", {"rich": None}):
        assert _confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is True


def test_confirm_restore_fallback_input_no() -> None:
    with patch("builtins.input", return_value="n"), patch.dict("sys.modules", {"rich": None}):
        assert _confirm_restore("backup.tar.zst", 1024, Path("/data/saves")) is False


def test_restore_command_uses_configured_saves(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup and an absolute configured saves directory
    backup = tmp_path / "backups" / "enshrouded-20260529-120000.tar.zst"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"backup")
    saves = tmp_path / "custom" / "saves"
    marker = tmp_path / "enshctl.pid"
    with (
        patch("sys.argv", ["enshctl", "restore", "--file", backup.name, "--yes"]),
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "generated_save_dir", return_value=saves),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "acquire_lock", return_value=3),
        patch.object(cmd, "release_lock"),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running the restore command
        result = cmd.run()

    # THEN the restore targets the configured saves directory and a sibling temp directory
    assert result == 0
    assert mock_restore.call_args.args[0] == backup
    kwargs = mock_restore.call_args.kwargs
    assert kwargs["saves_dir"] == saves
    assert kwargs["tmp_dir"] == saves.parent / "saves-restore-tmp"
    assert kwargs["space"] == SpaceGuard()


def test_restore_command_refuses_running_server(tmp_path: Path) -> None:
    import enshctl.commands.restore as cmd

    # GIVEN a selected Backup while the server is running
    backup = tmp_path / "backups" / "enshrouded-20260529-120000.tar.zst"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"backup")
    marker = tmp_path / "enshctl.pid"
    marker.touch()
    with (
        patch("sys.argv", ["enshctl", "restore", "--file", backup.name, "--yes"]),
        patch.object(cmd, "select", return_value=backup),
        patch.object(cmd, "PidFile", lambda: PidFile(marker)),
        patch.object(cmd, "restore_backup") as mock_restore,
    ):
        # WHEN running the restore command
        result = cmd.run()

    # THEN it refuses without touching the saves
    assert result == 1
    mock_restore.assert_not_called()
