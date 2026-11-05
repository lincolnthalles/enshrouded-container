"""Read-only save-signature probes for the Auto Pause gate."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SaveSignature:
    """Stable identity for one top-level save file."""

    path: Path
    size: int
    mtime_ns: int


def newest_save_signature(saves_dir: Path) -> SaveSignature | None:
    """Return the newest top-level ``*.ksd`` file signature, if one exists."""
    if not saves_dir.is_dir():
        return None
    newest: SaveSignature | None = None
    for path in saves_dir.glob("*.ksd"):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            logger.warning("Could not stat save file %s; ignoring it for Auto Pause", path)
            continue
        candidate = SaveSignature(path, stat.st_size, stat.st_mtime_ns)
        if newest is None or candidate.mtime_ns > newest.mtime_ns:
            newest = candidate
    return newest
