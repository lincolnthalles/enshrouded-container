"""Prune subcommand — enforce retention rules."""

import logging
from typing import TYPE_CHECKING

from enshctl.commands.parser import CommandParser
from enshctl.retention import RetentionPolicy
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None, argv: Sequence[str] = ()) -> int:
    parser = CommandParser("Prune old backups according to retention rules")
    parser.add_argument(
        "--dry-run", action="store_true", default=False, help="Show what would be deleted without deleting"
    )
    args = parser.parse(argv)

    settings = settings or load_settings()
    policy = RetentionPolicy.from_settings(settings)
    logger.info(
        "Pruning with retention: last=%d, hourly=%d, daily=%d, weekly=%d, monthly=%d, yearly=%d",
        policy.config.last,
        policy.config.hourly,
        policy.config.daily,
        policy.config.weekly,
        policy.config.monthly,
        policy.config.yearly,
    )

    results = policy.enforce(dry_run=args.dry_run)

    total = sum(len(paths) for paths in results.values())
    if total == 0:
        logger.info("No backups to prune")
        return 0

    if args.dry_run:
        for category, paths in results.items():
            for p in paths:
                logger.info("[DRY-RUN] Would delete %s from %s", p.name, category)
        logger.info("Dry-run: %d backup(s) would be deleted", total)
    else:
        for category, paths in results.items():
            if paths:
                logger.info("Pruned %d backup(s) from %s", len(paths), category)
        logger.info("Pruned %d backup(s) total", total)
    return 0
