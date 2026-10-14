"""Tests for retention engine."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from enshctl.backup import BackupFormat, BackupInfo
from enshctl.retention import (
    RetentionConfig,
    apply_retention,
)
from enshctl.settings import AppSettings


def _make_backup(name: str, day: int, hour: int = 12, minute: int = 0) -> BackupInfo:
    return BackupInfo(
        path=Path(f"/backups/live/{name}"),
        timestamp=datetime(2026, 5, day, hour, minute, 0, tzinfo=UTC),
        category="live",
        fmt=BackupFormat.ZSTD,
        size=1000,
    )


def test_keep_last_floor() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 20 + i, 12) for i in range(10)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=3)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept == 3


def test_keep_last_zero_disabled() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 20 + i) for i in range(5)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, daily=0)
    to_delete = apply_retention(backups, config)
    assert len(to_delete) == 0


def test_daily_retention() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 1 + i) for i in range(14)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, daily=7)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept == 7


def test_weekly_retention() -> None:
    backups = []
    for week in range(8):
        day = 1 + week * 7
        backups.append(_make_backup(f"b{week}.tar.zst", min(day, 30)))
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, weekly=4)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept == 4


def test_monthly_retention() -> None:
    backups = [
        BackupInfo(
            path=Path(f"/backups/live/b{i}.tar.zst"),
            timestamp=datetime(2026, min(i, 12), 1, 12, 0, 0, tzinfo=UTC),
            category="live",
            fmt=BackupFormat.ZSTD,
            size=1000,
        )
        for i in range(1, 13)
    ]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, monthly=3)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept == 3


def test_yearly_retention() -> None:
    backups = [
        BackupInfo(
            path=Path(f"/backups/live/b{i}.tar.zst"),
            timestamp=datetime(2020 + i, 6, 1, 12, 0, 0, tzinfo=UTC),
            category="live",
            fmt=BackupFormat.ZSTD,
            size=1000,
        )
        for i in range(8)
    ]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, yearly=5)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept == 5


def test_cascade_order() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 1 + i) for i in range(20)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=2, daily=3, weekly=2)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept >= 2


def test_keep_last_negative_one() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 1 + i) for i in range(5)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=-1)
    to_delete = apply_retention(backups, config)
    assert len(to_delete) == 0


def test_daily_negative_one() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 1 + i) for i in range(14)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, daily=-1)
    to_delete = apply_retention(backups, config)
    assert len(to_delete) == 0


def test_hourly_retention() -> None:
    backups = [_make_backup(f"b{i}.tar.zst", 1, 8 + i) for i in range(12)]
    backups.sort(key=lambda b: b.timestamp, reverse=True)
    config = RetentionConfig(last=0, hourly=3)
    to_delete = apply_retention(backups, config)
    kept = len(backups) - len(to_delete)
    assert kept == 3


def test_retention_config_from_settings_defaults() -> None:
    # GIVEN default settings
    # WHEN building a retention config
    # THEN the documented defaults apply
    config = RetentionConfig.from_settings(AppSettings())
    assert config == RetentionConfig(last=24)


def test_retention_config_from_settings_custom() -> None:
    # GIVEN custom keep values
    settings = replace(AppSettings(), backup_keep_last=5, backup_keep_daily=7)
    # WHEN building a retention config
    # THEN the values carry over
    config = RetentionConfig.from_settings(settings)
    assert config.last == 5
    assert config.daily == 7
