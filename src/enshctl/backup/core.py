"""Backup creation — disk guards and compression dispatch."""

import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup.catalog import BackupName
from enshctl.backup.format import ArchiveError, BackupFormat
from enshctl.utils import human_size

if TYPE_CHECKING:
    from enshctl.backup.category import Category
    from enshctl.disk_space import SpaceGuard
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupPlan:
    backup_dir: str
    saves_dir: Path
    fmt: BackupFormat
    level: int
    min_free_stop: int
    min_free_warn: int

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        saves_dir: Path,
        fmt: BackupFormat | None = None,
        level: int | None = None,
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
            saves_dir=saves_dir,
            fmt=resolved_fmt,
            level=resolved_level,
            min_free_stop=settings.backup_min_free_stop,
            min_free_warn=settings.backup_min_free_warn,
        )


def backup_needed(saves_dir: Path) -> bool:
    if not saves_dir.exists():
        return False
    try:
        return any(saves_dir.iterdir())
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
    category: Category,
    plan: BackupPlan,
    *,
    space: SpaceGuard,
) -> Path | None:
    try:
        saves_dir = plan.saves_dir.resolve(strict=False)
    except OSError, RuntimeError, ValueError:
        logger.warning("Cannot resolve saves directory %s, skipping backup", plan.saves_dir)
        return None
    if not backup_needed(saves_dir):
        logger.info("Save directory empty or missing, skipping backup")
        return None

    backup_dir = Path(plan.backup_dir) / category
    verdict = space.check(backup_dir, required_bytes=plan.min_free_stop)
    if not verdict.is_sufficient:
        logger.warning(
            "Disk space critical: %s free (minimum %s), skipping backup",
            human_size(verdict.free_bytes),
            human_size(plan.min_free_stop),
        )
        return None
    if verdict.free_bytes < plan.min_free_warn:
        logger.warning(
            "Disk space low: %s free (warning threshold %s)",
            human_size(verdict.free_bytes),
            human_size(plan.min_free_warn),
        )

    backup_dir.mkdir(parents=True, exist_ok=True)
    name = BackupName.now(category, plan.fmt)
    output_path = backup_dir / name.to_filename()

    is_complete = False
    try:
        plan.fmt.compress(saves_dir, output_path, plan.level)
    except ArchiveError as exc:
        logger.warning("Backup failed for %s: %s", output_path, exc)
        return None
    else:
        is_complete = True
    finally:
        if not is_complete:
            with suppress(OSError):
                output_path.unlink()

    logger.info("Backup created: %s", output_path)
    return output_path
