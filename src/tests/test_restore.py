"""Tests for restore command."""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.commands.restore import _check_server_running, _confirm_restore

if TYPE_CHECKING:
    from pathlib import Path


def test_check_server_running_marker_exists(tmp_path: Path) -> None:
    marker = tmp_path / ".server_running"
    marker.touch()
    with patch("enshctl.commands.restore.PIDFILE", marker):
        assert _check_server_running() is True


def test_check_server_running_marker_missing(tmp_path: Path) -> None:
    marker = tmp_path / ".server_running"
    with patch("enshctl.commands.restore.PIDFILE", marker):
        assert _check_server_running() is False


def test_confirm_restore_rich_yes() -> None:
    mock_confirm = MagicMock()
    mock_confirm.Confirm.ask.return_value = True
    mock_rich_console = MagicMock()
    modules = {"rich": MagicMock(), "rich.console": mock_rich_console, "rich.prompt": mock_confirm}
    with patch.dict("sys.modules", modules), patch("builtins.input"):
        assert _confirm_restore("backup.tar.zst", 1024) is True


def test_confirm_restore_rich_no() -> None:
    mock_confirm = MagicMock()
    mock_confirm.Confirm.ask.return_value = False
    mock_rich_console = MagicMock()
    modules = {"rich": MagicMock(), "rich.console": mock_rich_console, "rich.prompt": mock_confirm}
    with patch.dict("sys.modules", modules), patch("builtins.input"):
        assert _confirm_restore("backup.tar.zst", 1024) is False


def test_confirm_restore_fallback_input_yes() -> None:
    with patch("builtins.input", return_value="y"), patch.dict("sys.modules", {"rich": None}):
        assert _confirm_restore("backup.tar.zst", 1024) is True


def test_confirm_restore_fallback_input_no() -> None:
    with patch("builtins.input", return_value="n"), patch.dict("sys.modules", {"rich": None}):
        assert _confirm_restore("backup.tar.zst", 1024) is False
