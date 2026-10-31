"""Restore domain — atomic extract-to-tmp then swap into saves."""

import logging
import shutil
from typing import TYPE_CHECKING

from enshctl.backup import ArchiveError, decompress_archive
from enshctl.disk_space import SpaceVerdict
from enshctl.utils import human_size

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from enshctl.disk_space import SpaceGuard

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """Raised when a restore operation cannot be completed."""


def _verify_space(
    space: SpaceGuard,
    *,
    saves_dir: Path,
    tmp_dir: Path,
    free_before: int,
    saves_size: int,
    is_new_saves_dir: bool,
) -> None:
    tmp_size = space.tree_size(tmp_dir)
    verdict = SpaceVerdict(free_bytes=free_before, existing_bytes=saves_size, required_bytes=tmp_size)
    if verdict.is_sufficient:
        return
    logger.error(
        "Not enough disk space to complete restore. "
        "Extracted data: %s. Current saves: %s. Free space: %s. "
        "Need at least %s more. Free up space (e.g., prune backups).",
        human_size(verdict.required_bytes),
        human_size(verdict.existing_bytes),
        human_size(verdict.free_bytes),
        human_size(verdict.shortfall_bytes),
    )
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if is_new_saves_dir:
        shutil.rmtree(saves_dir, ignore_errors=True)
    raise RestoreError


def restore_backup(
    backup_path: Path,
    *,
    saves_dir: Path,
    tmp_dir: Path,
    space: SpaceGuard,
    extract: Callable[[Path, Path], None] = decompress_archive,
) -> None:
    """Extract to temp, verify space, clear saves, move, cleanup.

    The extract callable raises ArchiveError when extraction fails.
    """
    if saves_dir.is_symlink():
        logger.error("Restore refuses symlinked saves directory %s", saves_dir)
        raise RestoreError
    if tmp_dir == saves_dir or saves_dir.is_relative_to(tmp_dir) or tmp_dir.is_relative_to(saves_dir):
        logger.error("Restore temporary directory %s overlaps saves directory %s", tmp_dir, saves_dir)
        raise RestoreError

    # Clean up any pre-existing temp directory
    try:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError, ValueError:
        logger.exception("Cannot prepare restore temporary directory %s", tmp_dir)
        raise RestoreError from None

    saves_size = space.tree_size(saves_dir)
    free_before = space.disk_free(saves_dir)

    # Extract to temp directory first (saves untouched until extraction succeeds)
    logger.info("Extracting backup to temporary directory...")
    try:
        extract(backup_path, tmp_dir)
    except ArchiveError:
        logger.exception("Restore extraction failed")
        free = space.disk_free(tmp_dir)
        logger.exception(
            "Disk may be full. Free space: %s. Free up space (e.g., prune backups) and retry.",
            human_size(free),
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RestoreError from None

    # Compute sizes for the space check
    is_new_saves_dir = not saves_dir.exists()
    try:
        saves_dir.mkdir(parents=True, exist_ok=True)
    except OSError, ValueError:
        logger.exception("Cannot create saves directory %s", saves_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RestoreError from None
    _verify_space(
        space,
        saves_dir=saves_dir,
        tmp_dir=tmp_dir,
        free_before=free_before,
        saves_size=saves_size,
        is_new_saves_dir=is_new_saves_dir,
    )

    # Clear saves contents (don't rmtree the mount point itself)
    logger.info("Clearing current saves...")
    try:
        for item in saves_dir.iterdir():
            if item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # Move extracted data from tmp to saves
        logger.info("Moving restored data to saves directory...")
        for item in tmp_dir.iterdir():
            shutil.move(str(item), str(saves_dir / item.name))
    except OSError:
        logger.exception("Restore swap failed")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RestoreError from None

    # Cleanup tmp directory
    shutil.rmtree(tmp_dir, ignore_errors=True)
    logger.info("Restore complete")
