"""Backup subprocess runner — lowers priority, acquires lock, compresses, prunes."""

import argparse
import logging
import subprocess
from os import getpid, nice
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup import LOCK_FILE, acquire_lock, create_backup, release_lock, resolve_format
from enshctl.retention import RetentionConfig, prune_category
from enshctl.settings import load_settings

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

EXIT_SUCCESS = 0
EXIT_LOCK_HELD = 1
EXIT_ERROR = 2

_priority_state = {"warned": False}


def _make_priority_lowerer() -> Callable[[], None]:
    def inner() -> None:
        try:
            nice(19)
        except OSError:
            if not _priority_state["warned"]:
                logger.warning("SYS_NICE cap unavailable, backup runs at default CPU priority")
                _priority_state["warned"] = True
            else:
                logger.debug("SYS_NICE cap unavailable, backup runs at default CPU priority")

        try:
            subprocess.run(
                ["ionice", "-c3", "-p", str(getpid())],
                capture_output=True,
                check=True,
            )
        except OSError, subprocess.CalledProcessError:
            if not _priority_state["warned"]:
                logger.warning("ionice unavailable, backup runs at default IO priority")
                _priority_state["warned"] = True
            else:
                logger.debug("ionice unavailable, backup runs at default IO priority")

    return inner


_lower_priority = _make_priority_lowerer()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup subprocess runner")
    parser.add_argument("--format", default=None, type=str.lower, choices=["zstd", "gzip", "zip"])
    parser.add_argument("--level", type=int, default=None)
    parser.add_argument("--cold", action="store_true", default=False)
    parser.add_argument("--emergency", action="store_true", default=False)
    args, _ = parser.parse_known_args()

    _lower_priority()
    settings = load_settings()

    category = "live"
    if args.cold:
        category = "cold"
    elif args.emergency:
        category = "emergency"

    fmt = resolve_format(args.format) if args.format is not None else None

    lock_path = Path(settings.backup_dir) / LOCK_FILE
    fd = acquire_lock(str(lock_path), blocking=False)
    if fd is None:
        logger.info("Lock held by another process, skipping backup")
        return EXIT_LOCK_HELD

    try:
        result = create_backup(category, settings, fmt=fmt, level=args.level)
        if result is not None:
            config = RetentionConfig.from_settings(settings)
            cat_dir = Path(settings.backup_dir) / category
            deleted = prune_category(cat_dir, config, dry_run=False)
            if deleted:
                logger.info("Pruned %d backup(s) from %s", len(deleted), category)
    except OSError, ValueError:
        logger.exception("Backup failed")
        return EXIT_ERROR
    finally:
        release_lock(fd)

    return EXIT_SUCCESS


if __name__ == "__main__":
    main()
