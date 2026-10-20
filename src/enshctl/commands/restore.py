"""Restore subcommand — restore backup to /data/saves/."""

import logging
import sys
from pathlib import Path
from typing import Any, ClassVar, override

from enshctl.backup import (
    LOCK_FILE,
    SAVE_DIR,
    BackupInfo,
    acquire_lock,
    human_size,
    release_lock,
)
from enshctl.backup.catalog import scan_all, select
from enshctl.restore import RestoreError, restore_backup
from enshctl.settings import PIDFILE, RESTORE_TMP_DIR, load_settings

logger = logging.getLogger(__name__)


def _check_server_running() -> bool:
    return PIDFILE.exists()


def _confirm_restore(filename: str, size: int) -> bool:
    try:
        from rich.console import Console
        from rich.prompt import Confirm

        Console()
        return Confirm.ask(
            f"Restore [bold]{filename}[/bold] ({human_size(size)}) to /data/saves? This will erase current saves."
        )
    except ImportError:
        response = input(
            f"Restore {filename} ({human_size(size)}) to /data/saves? This will erase current saves. [y/N]: "
        )
        return response.strip().lower() == "y"


def run() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Restore a backup to /data/saves/")
    parser.add_argument("--file", default=None, help="Backup filename to restore")
    parser.add_argument("--when", default=None, help="Direction: last, 30m, 1h, 30d, 3M [:<category>]")
    parser.add_argument("--yes", action="store_true", default=False, help="Skip confirmation prompt")
    parser.add_argument("--list", action="store_true", default=False, dest="list_mode", help="List available backups")
    args, _ = parser.parse_known_args()

    settings = load_settings()
    base_dir = Path(settings.backup_dir)
    is_tty = sys.stdout.isatty()

    # List mode
    if args.list_mode or (not args.file and not args.when and not is_tty):
        backups = scan_all(base_dir)
        if not backups:
            logger.info("No backups found")
            return
        _list_backups(backups)
        return

    # Resolve backup to restore
    backup_path: Path | None = None
    if args.file:
        backup_path = select(base_dir, file=args.file)
    elif args.when:
        backup_path = select(base_dir, when=args.when)
    elif is_tty:
        backup_path = _interactive_restore(base_dir)

    if backup_path is None:
        logger.error("No matching backup found")
        sys.exit(1)

    # Pre-restore check
    if _check_server_running():
        logger.error("Cannot restore while server is running. Stop the server first.")
        sys.exit(1)

    # Confirm
    if not args.yes and not _confirm_restore(backup_path.name, backup_path.stat().st_size):
        logger.info("Restore cancelled")
        return

    # Perform restore
    lock_path = base_dir / LOCK_FILE
    fd = acquire_lock(str(lock_path), blocking=False)
    if fd is None:
        logger.error("Cannot acquire backup lock. Another backup operation is in progress.")
        sys.exit(1)

    try:
        restore_backup(backup_path, saves_dir=SAVE_DIR, tmp_dir=RESTORE_TMP_DIR)
    except RestoreError:
        sys.exit(1)
    finally:
        release_lock(fd)


def _list_backups(backups: list[Any]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table()
        table.add_column("Backup")
        table.add_column("Category")
        table.add_column("Size")
        table.add_column("Timestamp")
        for bi in backups:
            table.add_row(bi.path.name, bi.category, human_size(bi.size), bi.timestamp.isoformat())
        console.print(table)
    except ImportError:
        for bi in backups:
            print(f"{bi.path.name}  {bi.category}  {human_size(bi.size)}  {bi.timestamp.isoformat()}")


def _interactive_restore(base_dir: Path) -> Path | None:
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding, BindingType
        from textual.widgets import Footer, Header, ListItem, ListView, Static
    except ImportError:
        logger.exception("Interactive restore requires Textual. Use --file or --when instead.")
        sys.exit(1)

    class RestoreApp(App[None]):
        BINDINGS: ClassVar[list[BindingType]] = [
            Binding("q", "quit", "Quit"),
            Binding("escape", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._backups = scan_all(base_dir)
            self.selected: BackupInfo | None = None

        @override
        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("Select a backup to restore (q to quit)")
            yield ListView(*[ListItem(Static(f"{bi.path.name} ({human_size(bi.size)})")) for bi in self._backups])
            yield Footer()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            list_view = self.query_one(ListView)
            for idx, item in enumerate(list_view.children):
                if item is event.item:
                    self.selected = self._backups[idx]
                    self.exit()
                    return

        @override
        async def action_quit(self) -> None:
            self.exit()

    app = RestoreApp()
    app.run()
    return app.selected.path if app.selected is not None else None
