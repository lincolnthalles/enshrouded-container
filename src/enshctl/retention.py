"""Time-based retention engine inspired by Restic's retention model."""

import logging
from dataclasses import dataclass
from os import environ
from typing import TYPE_CHECKING

from enshctl.backup import BACKUP_DIRS, BackupInfo, get_backup_dir, parse_backup_filename

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RetentionConfig:
    last: int = 0
    hourly: int = 0
    daily: int = 0
    weekly: int = 0
    monthly: int = 0
    yearly: int = 0


def load_retention_config() -> RetentionConfig:
    def _env_int(key: str, default: int = 0) -> int:
        try:
            return int(environ.get(key, str(default)))
        except ValueError, TypeError:
            return default

    return RetentionConfig(
        last=_env_int("BACKUP_KEEP_LAST", 24),
        hourly=_env_int("BACKUP_KEEP_HOURLY", 0),
        daily=_env_int("BACKUP_KEEP_DAILY", 0),
        weekly=_env_int("BACKUP_KEEP_WEEKLY", 0),
        monthly=_env_int("BACKUP_KEEP_MONTHLY", 0),
        yearly=_env_int("BACKUP_KEEP_YEARLY", 0),
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
        k = key_fn(bi.timestamp)
        if k is not None and k not in seen:
            seen.add(k)
            keep.add(i)


def _week_key(dt: datetime) -> str:
    """Sunday-start calendar week key: YYYY-WW."""
    # strftime %U = Sunday-start week number (00-53)
    return dt.strftime("%Y-W%U")


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
    if not category_dir.exists():
        return []

    backups: list[BackupInfo] = []
    for p in sorted(category_dir.iterdir(), key=lambda x: x.name):
        if not p.is_file():
            continue
        parsed = parse_backup_filename(p.name)
        if parsed is None:
            continue
        ts, cat, fmt = parsed
        backups.append(BackupInfo(path=p, timestamp=ts, category=cat, fmt=fmt, size=p.stat().st_size))

    backups.sort(key=lambda bi: bi.timestamp, reverse=True)

    to_delete = apply_retention(backups, config)

    if not dry_run:
        for path in to_delete:
            try:
                path.unlink()
                logger.info("Pruned backup: %s", path)
            except OSError:
                logger.warning("Failed to prune %s", path, exc_info=True)

    return to_delete


def prune_all(config: RetentionConfig | None = None, dry_run: bool = False) -> dict[str, list[Path]]:
    """Apply retention to all categories.

    Returns dict mapping category name to list of deleted paths.
    """
    if config is None:
        config = load_retention_config()

    base_dir = get_backup_dir()
    results: dict[str, list[Path]] = {}

    for cat in BACKUP_DIRS:
        cat_dir = base_dir / cat
        deleted = prune_category(cat_dir, config, dry_run=dry_run)
        results[cat] = deleted

    return results
