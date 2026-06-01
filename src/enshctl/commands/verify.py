"""Verify subcommand — archive integrity checker."""

import logging
import sys
from typing import TYPE_CHECKING

from enshctl.backup import BACKUP_DIRS, get_backup_dir, human_size, verify_archive

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def run() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Verify backup archive integrity")
    parser.add_argument("--file", default=None, help="Specific backup file to verify")
    parser.add_argument("--all", action="store_true", default=False, dest="all_mode", help="Verify all backups")
    args, _ = parser.parse_known_args()

    base_dir = get_backup_dir()
    targets: list[Path] = []

    if args.file:
        for cat in BACKUP_DIRS:
            candidate = base_dir / cat / args.file
            if candidate.exists():
                targets.append(candidate)
                break
        if not targets:
            logger.error("Backup file not found: %s", args.file)
            sys.exit(1)
    else:
        for cat in BACKUP_DIRS:
            cat_dir = base_dir / cat
            if not cat_dir.exists():
                continue
            for p in sorted(cat_dir.iterdir()):
                if p.is_file() and p.suffix in (".zst", ".gz", ".zip"):
                    targets.append(p)

    if not targets:
        logger.info("No backups to verify")
        return

    is_tty = sys.stdout.isatty()
    results: list[tuple[str, int, str]] = []
    any_corrupt = False

    for path in targets:
        size = path.stat().st_size
        ok = verify_archive(path)
        status = "OK" if ok else "CORRUPT"
        results.append((path.name, size, status))
        if not ok:
            any_corrupt = True

    if is_tty:
        try:
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table()
            table.add_column("Backup")
            table.add_column("Size")
            table.add_column("Status")
            for name, size, status in results:
                style = "green" if status == "OK" else "red"
                table.add_row(name, human_size(size), f"[{style}]{status}[/{style}]")
            console.print(table)
        except ImportError:
            for name, size, status in results:
                print(f"{name}  {human_size(size)}  {status}")
    else:
        for name, size, status in results:
            print(f"{name}  {human_size(size)}  {status}")

    sys.exit(1 if any_corrupt else 0)
