"""Shared command table rendering with a plain-text fallback."""

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class Cell:
    text: str
    style: str | None = None


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Cell]],
    *,
    is_tty: bool | None = None,
) -> None:
    """Render rows as a Rich table on a TTY, or plain columns otherwise."""
    tty = sys.stdout.isatty() if is_tty is None else is_tty
    if tty:
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.text import Text
        except ImportError:
            pass
        else:
            table = Table()
            for header in headers:
                table.add_column(header)
            for row in rows:
                rendered = [Text(cell.text, style=cell.style) if cell.style else cell.text for cell in row]
                table.add_row(*rendered)
            Console().print(table)
            return

    for row in rows:
        print("  ".join(cell.text for cell in row))
