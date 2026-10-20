"""Archive compression, decompression, and verification."""

import logging
from typing import TYPE_CHECKING

from enshctl.backup.format import ARCHIVE_ERRORS, detect_format

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def decompress_archive(archive_path: Path, target_dir: Path) -> None:
    fmt = detect_format(archive_path)
    fmt.decompress()(archive_path, target_dir)


def verify_archive(archive_path: Path) -> bool:
    """Stream all members to EOF to verify archive integrity.

    Returns True if intact, False if corrupt.
    """
    fmt = detect_format(archive_path)
    try:
        return fmt.verify()(archive_path)
    except ARCHIVE_ERRORS as exc:
        logger.warning("Verification failed for %s: %s", archive_path, exc)
        return False
