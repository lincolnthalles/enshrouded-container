"""Prune subcommand — enforce retention rules."""

import logging

from enshctl.retention import load_retention_config, prune_all

logger = logging.getLogger(__name__)


def run() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Prune old backups according to retention rules")
    parser.add_argument(
        "--dry-run", action="store_true", default=False, help="Show what would be deleted without deleting"
    )
    args, _ = parser.parse_known_args()

    config = load_retention_config()
    logger.info(
        "Pruning with retention: last=%d, hourly=%d, daily=%d, weekly=%d, monthly=%d, yearly=%d",
        config.last,
        config.hourly,
        config.daily,
        config.weekly,
        config.monthly,
        config.yearly,
    )

    results = prune_all(config, dry_run=args.dry_run)

    total = sum(len(paths) for paths in results.values())
    if total == 0:
        logger.info("No backups to prune")
        return

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
