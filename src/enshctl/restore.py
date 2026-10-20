"""Restore domain — atomic extract-to-tmp then swap into saves."""

import logging
import shutil
from typing import TYPE_CHECKING

from enshctl.backup import ARCHIVE_ERRORS, decompress_archive
from enshctl.utils import human_size

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """Raised when a restore operation cannot be completed."""


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


def restore_backup(
    backup_path: Path,
    *,
    saves_dir: Path,
    tmp_dir: Path,
    extract: Callable[[Path, Path], None] = decompress_archive,
    disk_free: Callable[[Path], int] = _disk_free,
) -> None:
    """Extract to temp, verify space, clear saves, move, cleanup."""
    # Clean up any pre-existing temp directory
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Extract to temp directory first (saves untouched until extraction succeeds)
    logger.info("Extracting backup to temporary directory...")
    try:
        extract(backup_path, tmp_dir)
    except ARCHIVE_ERRORS:
        logger.exception("Restore extraction failed")
        free = disk_free(saves_dir)
        logger.exception(
            "Disk may be full. Free space: %s. Free up space (e.g., prune backups) and retry.",
            human_size(free),
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RestoreError from None

    # Compute sizes for the space check
    tmp_size = sum(f.stat().st_size for f in tmp_dir.rglob("*") if f.is_file())
    saves_size = sum(f.stat().st_size for f in saves_dir.rglob("*") if f.is_file()) if saves_dir.exists() else 0
    free_now = disk_free(saves_dir)

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
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RestoreError from None

    # Clear saves contents (don't rmtree the mount point itself)
    logger.info("Clearing current saves...")
    if saves_dir.exists():
        for item in saves_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # Move extracted data from tmp to saves
    logger.info("Moving restored data to saves directory...")
    for item in tmp_dir.iterdir():
        shutil.move(str(item), str(saves_dir / item.name))

    # Cleanup tmp directory
    shutil.rmtree(tmp_dir, ignore_errors=True)
    logger.info("Restore complete")
