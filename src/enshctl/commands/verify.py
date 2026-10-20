"""Verify subcommand — archive integrity checker."""

import logging
import sys
from pathlib import Path

from enshctl.backup import verify_archive
from enshctl.backup.catalog import scan_all, scan_stray, select
from enshctl.settings import AppSettings, load_settings
from enshctl.utils import human_size

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Verify backup archive integrity")
    parser.add_argument("--file", default=None, help="Specific backup file to verify")
    parser.add_argument("--all", action="store_true", default=False, dest="all_mode", help="Verify all backups")
    args, _ = parser.parse_known_args()

    settings = settings or load_settings()
    base_dir = Path(settings.backup_dir)
    targets: list[Path] = []
    skipped: list[Path] = []

    if args.file:
        found = select(base_dir, file=args.file)
        if found is not None:
            targets.append(found)
        if not targets:
            logger.error("Backup file not found: %s", args.file)
            sys.exit(1)
    else:
        for info in scan_all(base_dir):
            targets.append(info.path)
        skipped = scan_stray(base_dir)
        for stray in skipped:
            logger.warning("Skipping non-backup archive (unexpected filename): %s", stray.name)

    if skipped:
        logger.info("Skipped %d non-backup archive(s)", len(skipped))

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
