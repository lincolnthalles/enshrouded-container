"""Verify subcommand — archive integrity checker."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup.catalog import scan_all, scan_stray, select
from enshctl.backup.format import verify_archive
from enshctl.commands.parser import CommandParser
from enshctl.commands.table import Cell, render_table
from enshctl.settings import AppSettings, load_settings
from enshctl.utils import human_size

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None, argv: Sequence[str] = ()) -> int:
    parser = CommandParser("Verify backup archive integrity")
    parser.add_argument("--file", default=None, help="Specific backup file to verify")
    parser.add_argument("--all", action="store_true", default=False, dest="all_mode", help="Verify all backups")
    args = parser.parse(argv)

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
            return 1
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
        return 0

    results: list[tuple[str, int, str]] = []
    any_corrupt = False

    for path in targets:
        size = path.stat().st_size
        ok = verify_archive(path)
        status = "OK" if ok else "CORRUPT"
        results.append((path.name, size, status))
        if not ok:
            any_corrupt = True

    rows = [
        [
            Cell(name),
            Cell(human_size(size)),
            Cell(status, "green" if status == "OK" else "red"),
        ]
        for name, size, status in results
    ]
    render_table(("Backup", "Size", "Status"), rows)

    return 1 if any_corrupt else 0
