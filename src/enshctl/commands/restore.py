"""Restore subcommand — restore a Backup to the configured saves directory."""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup.catalog import scan_all, select
from enshctl.backup.locking import LOCK_FILE, acquire_lock, release_lock
from enshctl.commands.parser import CommandParser
from enshctl.commands.restore_tui import select_backup as select_backup_impl
from enshctl.commands.table import Cell, render_table
from enshctl.config import generated_save_directories
from enshctl.disk_space import SpaceGuard
from enshctl.pidfile import PidFile
from enshctl.restore import RestoreError, restore_backup
from enshctl.settings import AppSettings, load_settings
from enshctl.utils import human_size

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from enshctl.backup.catalog import BackupInfo

logger = logging.getLogger(__name__)


def _check_server_running(pid_file: PidFile | None = None) -> bool:
    return (pid_file or PidFile()).is_active()


def confirm_restore(filename: str, size: int, saves_dir: Path) -> bool:
    try:
        from rich.console import Console
        from rich.prompt import Confirm

        Console()
        return Confirm.ask(
            f"Restore [bold]{filename}[/bold] ({human_size(size)}) to {saves_dir}? This will erase current saves."
        )
    except ImportError:
        response = input(
            f"Restore {filename} ({human_size(size)}) to {saves_dir}? This will erase current saves. [y/N]: "
        )
        return response.strip().lower() == "y"


@dataclass(frozen=True)
class RestoreSeams:
    """UI adapters for one restore invocation."""

    confirm_restore: Callable[[str, int, Path], bool] = confirm_restore
    select_backup: Callable[[Sequence[BackupInfo]], BackupInfo | None] = select_backup_impl


def run(
    settings: AppSettings | None = None,
    argv: Sequence[str] = (),
    *,
    seams: RestoreSeams | None = None,
) -> int:
    parser = CommandParser("Restore a Backup to the configured saves directory")
    parser.add_argument("--file", default=None, help="Backup filename to restore")
    parser.add_argument("--when", default=None, help="Direction: last, 30m, 1h, 30d, 3M [:<category>]")
    parser.add_argument("--yes", action="store_true", default=False, help="Skip confirmation prompt")
    parser.add_argument("--list", action="store_true", default=False, dest="list_mode", help="List available backups")
    args = parser.parse(argv)

    settings = settings or load_settings()
    base_dir = Path(settings.backup_dir)
    is_tty = sys.stdout.isatty()
    resolved = seams or RestoreSeams()

    # List mode
    if args.list_mode or (not args.file and not args.when and not is_tty):
        backups = scan_all(base_dir)
        if not backups:
            logger.info("No backups found")
            return 0
        _list_backups(backups)
        return 0

    # Resolve backup to restore
    backup_path: Path | None = None
    try:
        if args.file:
            backup_path = select(base_dir, file=args.file)
        elif args.when:
            backup_path = select(base_dir, when=args.when)
        elif is_tty:
            selected = resolved.select_backup(scan_all(base_dir))
            backup_path = selected.path if selected is not None else None
    except RestoreError:
        return 1

    if backup_path is None:
        logger.error("No matching backup found")
        return 1

    # Pre-restore check
    if _check_server_running():
        logger.error("Cannot restore while server is running. Stop the server first.")
        return 1

    # Confirm
    save_dirs = generated_save_directories(settings=settings)
    saves_dir = save_dirs.saves_dir
    if not args.yes and not resolved.confirm_restore(backup_path.name, backup_path.stat().st_size, saves_dir):
        logger.info("Restore cancelled")
        return 0

    # Perform restore
    lock_path = base_dir / LOCK_FILE
    fd = acquire_lock(str(lock_path), blocking=False)
    if fd is None:
        logger.error("Cannot acquire backup lock. Another backup operation is in progress.")
        return 1

    try:
        restore_backup(
            backup_path,
            saves_dir=saves_dir,
            tmp_dir=save_dirs.restore_tmp_dir,
            space=SpaceGuard(),
        )
    except RestoreError:
        return 1
    finally:
        release_lock(fd)
    return 0


def _list_backups(backups: list[BackupInfo]) -> None:
    rows = [
        [
            Cell(bi.path.name),
            Cell(bi.name.category),
            Cell(human_size(bi.size)),
            Cell(bi.name.timestamp.isoformat()),
        ]
        for bi in backups
    ]
    render_table(("Backup", "Category", "Size", "Timestamp"), rows)
