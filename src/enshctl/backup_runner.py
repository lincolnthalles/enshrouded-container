"""Backup subprocess runner — lowers priority, acquires lock, compresses, prunes."""

import argparse
import logging
import subprocess
import time
from os import getpid, nice
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup import LOCK_FILE, acquire_lock, create_backup, release_lock, resolve_format
from enshctl.backup.core import BackupPlan
from enshctl.backup_protocol import BackupOutcome, BackupRequest, add_arguments
from enshctl.retention import RetentionConfig, prune_category
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

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


def main(settings: AppSettings | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup subprocess runner")
    add_arguments(parser)
    args, _ = parser.parse_known_args()
    request = BackupRequest.from_argv(args)

    _lower_priority()
    resolved = settings or load_settings()

    category = request.category

    fmt = resolve_format(args.format) if args.format is not None else None

    lock_path = Path(resolved.backup_dir) / LOCK_FILE
    fd = acquire_lock(str(lock_path), blocking=False)
    waited = False
    if fd is None and request.wait_seconds > 0:
        waited = True
        deadline = time.monotonic() + request.wait_seconds
        while fd is None and time.monotonic() < deadline:
            time.sleep(1)
            fd = acquire_lock(str(lock_path), blocking=False)
    if fd is None:
        if waited:
            logger.warning("Backup lock still held after %ds wait, skipping backup", request.wait_seconds)
        else:
            logger.info("Lock held by another process, skipping backup")
        return BackupOutcome.LOCK_HELD

    try:
        plan = BackupPlan.from_settings(resolved, fmt=fmt, level=args.level)
        result = create_backup(category, plan)
        if result is not None:
            config = RetentionConfig.from_settings(resolved)
            cat_dir = Path(resolved.backup_dir) / category
            deleted = prune_category(cat_dir, config, dry_run=False)
            if deleted:
                logger.info("Pruned %d backup(s) from %s", len(deleted), category)
    except OSError, ValueError:
        logger.exception("Backup failed")
        return BackupOutcome.ERROR
    finally:
        release_lock(fd)

    return BackupOutcome.SUCCESS


if __name__ == "__main__":
    main()
