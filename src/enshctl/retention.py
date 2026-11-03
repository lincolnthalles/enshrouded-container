"""Time-based retention engine inspired by Restic's retention model."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.backup.catalog import BackupInfo, scan_dir
from enshctl.backup.category import CATEGORIES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from enshctl.backup.category import Category
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass
class RetentionConfig:
    last: int = 0
    hourly: int = 0
    daily: int = 0
    weekly: int = 0
    monthly: int = 0
    yearly: int = 0

    @classmethod
    def from_settings(cls, settings: AppSettings) -> RetentionConfig:
        return cls(
            last=settings.backup_keep_last,
            hourly=settings.backup_keep_hourly,
            daily=settings.backup_keep_daily,
            weekly=settings.backup_keep_weekly,
            monthly=settings.backup_keep_monthly,
            yearly=settings.backup_keep_yearly,
        )


def _apply_keep_last(backups: list[BackupInfo], config: RetentionConfig, keep: set[int]) -> None:
    if config.last == 0:
        return
    if config.last == -1:
        for i in range(len(backups)):
            keep.add(i)
        return
    for i in range(min(config.last, len(backups))):
        keep.add(i)


def _apply_time_bucket(
    backups: list[BackupInfo], key_fn: Callable[[datetime], str | None], max_count: int, keep: set[int]
) -> None:
    if max_count == 0:
        return
    seen: set[str] = set()
    for i, bi in enumerate(backups):
        if max_count > 0 and len(seen) >= max_count:
            break
        k = key_fn(bi.name.timestamp)
        if k is not None and k not in seen:
            seen.add(k)
            keep.add(i)


def _week_key(dt: datetime) -> str:
    """Sunday-start calendar week key: the ISO date of the week's Sunday.

    Scoped to the actual week, not the year — a Sunday-start week spanning
    January 1st keys to a single Sunday instead of splitting across years.
    """
    sunday = (dt - timedelta(days=(dt.weekday() + 1) % 7)).date()
    return sunday.isoformat()


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _year_key(dt: datetime) -> str:
    return dt.strftime("%Y")


def apply_retention(backups: list[BackupInfo], config: RetentionConfig) -> list[Path]:
    """Apply retention rules and return list of backup paths to delete.

    Backups should be sorted newest-first.
    """
    if not backups:
        return []

    # Safety gate: if no rule is configured, prune nothing
    if config.last == 0 and not any((config.hourly, config.daily, config.weekly, config.monthly, config.yearly)):
        return []

    keep: set[int] = set()

    _apply_keep_last(backups, config, keep)
    _apply_time_bucket(backups, lambda ts: ts.strftime("%Y-%m-%dT%H:00"), config.hourly, keep)
    _apply_time_bucket(backups, lambda ts: ts.strftime("%Y-%m-%d"), config.daily, keep)
    _apply_time_bucket(backups, _week_key, config.weekly, keep)
    _apply_time_bucket(backups, _month_key, config.monthly, keep)
    _apply_time_bucket(backups, _year_key, config.yearly, keep)

    to_delete: list[Path] = []
    for i, bi in enumerate(backups):
        if i not in keep:
            to_delete.append(bi.path)

    return to_delete


def prune_category(category_dir: Path, config: RetentionConfig, dry_run: bool = False) -> list[Path]:
    """Apply retention to one category directory.

    Returns list of paths that were (or would be) deleted.
    """
    backups = scan_dir(category_dir)
    to_delete = apply_retention(backups, config)

    if not dry_run:
        for path in to_delete:
            try:
                path.unlink()
                logger.info("Pruned backup: %s", path)
            except OSError:
                logger.warning("Failed to prune %s", path, exc_info=True)

    return to_delete


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention rules bound to the Backup base directory."""

    config: RetentionConfig
    base_dir: Path

    @classmethod
    def from_settings(cls, settings: AppSettings) -> RetentionPolicy:
        return cls(config=RetentionConfig.from_settings(settings), base_dir=Path(settings.backup_dir))

    def enforce(
        self,
        *,
        categories: Iterable[Category] = CATEGORIES,
        dry_run: bool = False,
    ) -> dict[Category, list[Path]]:
        """Apply retention to the requested Categories and return deleted paths."""
        return {
            category: prune_category(self.base_dir / category, self.config, dry_run=dry_run) for category in categories
        }
