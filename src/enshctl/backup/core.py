"""Backup creation — disk guards and compression dispatch."""

import logging
import shutil
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup.archive import ARCHIVE_ERRORS
from enshctl.backup.catalog import _local_now
from enshctl.backup.format import BackupFormat, category_suffix
from enshctl.settings import SAVE_DIR
from enshctl.utils import human_size

if TYPE_CHECKING:
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


def backup_needed() -> bool:
    if not SAVE_DIR.exists():
        return False
    try:
        return any(SAVE_DIR.iterdir())
    except OSError:
        return False


def resolve_format(raw: str) -> BackupFormat:
    try:
        return BackupFormat(raw.lower())
    except ValueError:
        logger.warning("Unknown BACKUP_FORMAT '%s', falling back to zstd", raw)
        return BackupFormat.ZSTD


def resolve_level(fmt: BackupFormat, raw: str) -> int:
    if raw:
        try:
            level = int(raw)
        except ValueError, TypeError:
            level = fmt.get_default_level()
        return fmt.clamp_level(level)
    return fmt.get_default_level()


def create_backup(
    category: str,
    settings: AppSettings,
    *,
    fmt: BackupFormat | None = None,
    level: int | None = None,
) -> Path | None:
    if not backup_needed():
        logger.info("Save directory empty or missing, skipping backup")
        return None

    backup_dir = Path(settings.backup_dir) / category
    backup_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(backup_dir).free
    min_free_stop = settings.backup_min_free_stop
    min_free_warn = settings.backup_min_free_warn
    if free < min_free_stop:
        logger.warning(
            "Disk space critical: %s free (minimum %s), skipping backup",
            human_size(free),
            human_size(min_free_stop),
        )
        return None
    if free < min_free_warn:
        logger.warning("Disk space low: %s free (warning threshold %s)", human_size(free), human_size(min_free_warn))

    if fmt is None:
        fmt = resolve_format(settings.backup_format)
    if level is None:
        level = resolve_level(fmt, "" if settings.backup_level is None else str(settings.backup_level))
    else:
        level = fmt.clamp_level(level)
    timestamp = _local_now().strftime("%Y%m%d-%H%M%S")

    suffix = category_suffix(category)

    ext = fmt.get_extension()
    filename = f"enshrouded-{timestamp}{suffix}{ext}"
    output_path = backup_dir / filename

    compress = fmt.compress()

    try:
        compress(SAVE_DIR, output_path, level)
    except ARCHIVE_ERRORS as exc:
        logger.warning("Backup failed for %s: %s", output_path, exc)
        with suppress(OSError):
            output_path.unlink()
        return None
    else:
        logger.info("Backup created: %s", output_path)
        return output_path
