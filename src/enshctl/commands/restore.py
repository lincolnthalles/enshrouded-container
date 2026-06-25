"""Restore subcommand — restore backup to /data/saves/."""

import logging
import shutil
import sys
import tarfile
from typing import TYPE_CHECKING, Any, ClassVar, override

from enshctl.backup import (
    LOCK_FILE,
    SAVE_DIR,
    BackupInfo,
    acquire_lock,
    decompress_archive,
    get_backup_dir,
    human_size,
    list_backups,
    release_lock,
    select_backup,
)
from enshctl.settings import PIDFILE

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """Raised when a restore operation cannot be completed."""


RESTORE_TMP_DIR = SAVE_DIR.parent / "saves-restore-tmp"


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

    is_tty = sys.stdout.isatty()

    # List mode
    if args.list_mode or (not args.file and not args.when and not is_tty):
        backups = list_backups(get_backup_dir(), when=None)
        if not backups:
            logger.info("No backups found")
            return
        _list_backups(backups)
        return

    # Resolve backup to restore
    backup_path: Path | None = None
    if args.file:
        backup_path = select_backup(file=args.file)
    elif args.when:
        backup_path = select_backup(when=args.when)
    elif is_tty:
        backup_path = _interactive_restore()

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
    lock_path = get_backup_dir() / LOCK_FILE
    fd = acquire_lock(str(lock_path), blocking=False)
    if fd is None:
        logger.error("Cannot acquire backup lock. Another backup operation is in progress.")
        sys.exit(1)

    try:
        _perform_restore(backup_path)
    except RestoreError:
        sys.exit(1)
    finally:
        release_lock(fd)


def _perform_restore(backup_path: Path) -> None:
    """Extract to temp, verify space, clear saves, move, cleanup."""
    # Clean up any pre-existing temp directory
    if RESTORE_TMP_DIR.exists():
        shutil.rmtree(RESTORE_TMP_DIR)
    RESTORE_TMP_DIR.mkdir(parents=True, exist_ok=True)

    # Extract to temp directory first (saves untouched until extraction succeeds)
    logger.info("Extracting backup to temporary directory...")
    try:
        decompress_archive(backup_path, RESTORE_TMP_DIR)
    except OSError, EOFError, tarfile.TarError:
        logger.exception("Restore extraction failed")
        free = shutil.disk_usage(SAVE_DIR).free
        logger.exception(
            "Disk may be full. Free space: %s. Free up space (e.g., prune backups) and retry.",
            human_size(free),
        )
        shutil.rmtree(RESTORE_TMP_DIR, ignore_errors=True)
        raise RestoreError from None

    # Compute sizes for the space check
    tmp_size = sum(f.stat().st_size for f in RESTORE_TMP_DIR.rglob("*") if f.is_file())
    saves_size = sum(f.stat().st_size for f in SAVE_DIR.rglob("*") if f.is_file()) if SAVE_DIR.exists() else 0
    free_now = shutil.disk_usage(SAVE_DIR).free

    # Verify space after clearing saves
    if free_now + saves_size < tmp_size:
        shortfall = tmp_size - free_now - saves_size
        logger.error(
            "Not enough disk space to complete restore. "
            "Extracted data: %s. Current saves: %s. Free space: %s. "
            "Need at least %s more. Free up space (e.g., prune backups).",
            human_size(tmp_size),
            human_size(saves_size),
            human_size(free_now),
            human_size(shortfall),
        )
        shutil.rmtree(RESTORE_TMP_DIR, ignore_errors=True)
        raise RestoreError from None

    # Clear saves contents (don't rmtree the mount point itself)
    logger.info("Clearing current saves...")
    if SAVE_DIR.exists():
        for item in SAVE_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # Move extracted data from tmp to saves
    logger.info("Moving restored data to saves directory...")
    for item in RESTORE_TMP_DIR.iterdir():
        shutil.move(str(item), str(SAVE_DIR / item.name))

    # Cleanup tmp directory
    shutil.rmtree(RESTORE_TMP_DIR, ignore_errors=True)
    logger.info("Restore complete")


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


def _interactive_restore() -> Path | None:
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
            self._backups = list_backups(get_backup_dir())
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
