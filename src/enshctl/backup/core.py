"""Backup creation — disk guards and compression dispatch."""

import logging
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup.archive import ARCHIVE_ERRORS
from enshctl.backup.catalog import _local_now
from enshctl.backup.format import BackupFormat, category_suffix
from enshctl.paths import SAVE_DIR
from enshctl.utils import human_size

if TYPE_CHECKING:
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupPlan:
    backup_dir: str
    fmt: BackupFormat
    level: int
    min_free_stop: int
    min_free_warn: int

    @classmethod
    def from_settings(
        cls, settings: AppSettings, *, fmt: BackupFormat | None = None, level: int | None = None
    ) -> BackupPlan:
        resolved_fmt = fmt if fmt is not None else resolve_format(settings.backup_format)
        if level is None:
            resolved_level = resolve_level(
                resolved_fmt, "" if settings.backup_level is None else str(settings.backup_level)
            )
        else:
            resolved_level = resolved_fmt.clamp_level(level)
        return cls(
            backup_dir=settings.backup_dir,
            fmt=resolved_fmt,
            level=resolved_level,
            min_free_stop=settings.backup_min_free_stop,
            min_free_warn=settings.backup_min_free_warn,
        )


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
    plan: BackupPlan,
) -> Path | None:
    if not backup_needed():
        logger.info("Save directory empty or missing, skipping backup")
        return None

    backup_dir = Path(plan.backup_dir) / category
    backup_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(backup_dir).free
    if free < plan.min_free_stop:
        logger.warning(
            "Disk space critical: %s free (minimum %s), skipping backup",
            human_size(free),
            human_size(plan.min_free_stop),
        )
        return None
    if free < plan.min_free_warn:
        logger.warning(
            "Disk space low: %s free (warning threshold %s)", human_size(free), human_size(plan.min_free_warn)
        )

    timestamp = _local_now().strftime("%Y%m%d-%H%M%S")

    suffix = category_suffix(category)

    ext = plan.fmt.get_extension()
    filename = f"enshrouded-{timestamp}{suffix}{ext}"
    output_path = backup_dir / filename

    compress = plan.fmt.compress()

    try:
        compress(SAVE_DIR, output_path, plan.level)
    except ARCHIVE_ERRORS as exc:
        logger.warning("Backup failed for %s: %s", output_path, exc)
        with suppress(OSError):
            output_path.unlink()
        return None
    else:
        logger.info("Backup created: %s", output_path)
        return output_path
