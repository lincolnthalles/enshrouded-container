"""Backup creation — disk guards and compression dispatch."""

import logging
import shutil
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import zstandard

from enshctl.backup.catalog import BackupFormat, _local_now
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
    from enshctl.backup.archive import _compress_gzip, _compress_zip, _compress_zstd  # noqa: PLC0415

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

    suffix = ""
    if category == "cold":
        suffix = "-cold"
    elif category == "emergency":
        suffix = "-emergency"

    ext = fmt.get_extension()
    filename = f"enshrouded-{timestamp}{suffix}{ext}"
    output_path = backup_dir / filename

    compressors = {
        BackupFormat.ZSTD: _compress_zstd,
        BackupFormat.GZIP: _compress_gzip,
        BackupFormat.ZIP: _compress_zip,
    }

    compress = compressors[fmt]

    try:
        compress(SAVE_DIR, output_path, level)
    except (OSError, zstandard.ZstdError, zipfile.BadZipFile) as exc:
        logger.warning("Backup failed for %s: %s", output_path, exc)
        with suppress(OSError):
            output_path.unlink()
        return None
    else:
        logger.info("Backup created: %s", output_path)
        return output_path
