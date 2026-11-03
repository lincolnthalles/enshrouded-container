"""Tests for shared subcommand table rendering."""

from typing import TYPE_CHECKING
from unittest.mock import patch

from enshctl.commands.table import Cell, render_table

if TYPE_CHECKING:
    import pytest


def test_render_table_plain_non_tty(capsys: pytest.CaptureFixture[str]) -> None:
    # GIVEN styled cells and plain output requested
    rows = [[Cell("backup.tar.zst"), Cell("1 KB", "green")]]

    # WHEN rendering for a non-TTY
    render_table(("Backup", "Size"), rows, is_tty=False)

    # THEN cell text prints without headers or styling
    assert capsys.readouterr().out == "backup.tar.zst  1 KB\n"


def test_render_table_detects_non_tty(capsys: pytest.CaptureFixture[str]) -> None:
    # GIVEN a non-TTY stdout
    rows = [[Cell("backup.tar.zst"), Cell("1 KB", "green")]]

    with patch("enshctl.commands.table.sys.stdout.isatty", return_value=False):
        # WHEN rendering without an explicit TTY choice
        render_table(("Backup", "Size"), rows)

    # THEN the plain fallback is used
    assert capsys.readouterr().out == "backup.tar.zst  1 KB\n"


def test_render_table_rich_on_tty(capsys: pytest.CaptureFixture[str]) -> None:
    # GIVEN styled cells and a TTY
    rows = [[Cell("backup.tar.zst"), Cell("1 KB", "green")]]

    # WHEN rendering on a TTY
    render_table(("Backup", "Size"), rows, is_tty=True)

    # THEN the Rich table includes its box drawing and cell text
    output = capsys.readouterr().out
    assert "\u250f" in output
    assert "Backup" in output
    assert "Size" in output
    assert "backup.tar.zst" in output
    assert "1 KB" in output
