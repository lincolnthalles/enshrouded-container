"""Tests for prune command and retention pruning."""

from typing import TYPE_CHECKING

from enshctl.retention import RetentionConfig, prune_category

if TYPE_CHECKING:
    from pathlib import Path


def _make_backup_file(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"\\x00" * 100)
    return p


def test_prune_keeps_all_when_keep_last_negative_one(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260502-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260503-120000.tar.zst")
    config = RetentionConfig(last=-1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 0


def test_prune_keeps_last_n(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260502-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260503-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260504-120000.tar.zst")
    config = RetentionConfig(last=2)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 2


def test_prune_deletes_files_on_non_dry_run(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    f1 = _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    f2 = _make_backup_file(cat_dir, "enshrouded-20260502-120000.tar.zst")
    f3 = _make_backup_file(cat_dir, "enshrouded-20260503-120000.tar.zst")
    config = RetentionConfig(last=1)
    deleted = prune_category(cat_dir, config, dry_run=False)
    assert len(deleted) == 2
    assert not f1.exists()
    assert not f2.exists()
    assert f3.exists()


def test_prune_with_daily_retention(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260501-140000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260502-120000.tar.zst")
    config = RetentionConfig(daily=1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 2


def test_prune_with_weekly_retention(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260508-120000.tar.zst")
    config = RetentionConfig(weekly=1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 1


def test_prune_with_monthly_retention(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260401-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    config = RetentionConfig(monthly=1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 1


def test_prune_with_yearly_retention(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20250501-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    config = RetentionConfig(yearly=1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 1


def test_prune_empty_dir(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    config = RetentionConfig(last=5)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 0


def test_prune_nonexistent_dir(tmp_path: Path) -> None:
    cat_dir = tmp_path / "nonexistent"
    config = RetentionConfig(last=5)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 0


def test_prune_ignores_non_backup_files(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    (cat_dir / "not-a-backup.txt").write_bytes(b"junk")
    config = RetentionConfig(last=1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 0


def test_prune_cascade_order(tmp_path: Path) -> None:
    cat_dir = tmp_path / "live"
    cat_dir.mkdir()
    _make_backup_file(cat_dir, "enshrouded-20260101-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260201-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260301-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260401-120000.tar.zst")
    _make_backup_file(cat_dir, "enshrouded-20260501-120000.tar.zst")
    config = RetentionConfig(last=1, daily=1, weekly=1, monthly=1, yearly=1)
    deleted = prune_category(cat_dir, config, dry_run=True)
    assert len(deleted) == 4
