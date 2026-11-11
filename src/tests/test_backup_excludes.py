"""Tests for the backup exclude-list filter."""

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from enshctl.backup.core import BackupPlan, create_backup
from enshctl.backup.excludes import BackupExcludes
from enshctl.backup.format import BackupFormat, decompress_archive
from enshctl.disk_space import SpaceGuard
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path


def _saves_tree(tmp_path: Path) -> Path:
    saves = tmp_path / "saves"
    (saves / "backup").mkdir(parents=True)
    (saves / "migrated" / "nested").mkdir(parents=True)
    (saves / "world0.ksd").write_bytes(b"world")
    (saves / "backup" / "world0.ksd.backup-0").write_bytes(b"latest")
    (saves / "backup" / "world0.ksd.backup-1").write_bytes(b"stale")
    (saves / "backup" / "world0.ksd.backup-9").write_bytes(b"stale")
    (saves / "migrated" / "old.dat").write_bytes(b"old")
    (saves / "migrated" / "nested" / "deep.dat").write_bytes(b"deep")
    return saves


def test_default_excludes_stale_but_keeps_active() -> None:
    # GIVEN the default exclude-list
    # WHEN checking saves-tree members
    # THEN migrated and stale server backups drop while active content stays
    excludes = BackupExcludes.from_raw(AppSettings().backup_exclude)
    assert excludes.is_excluded("migrated/old.dat") is True
    assert excludes.is_excluded("migrated/nested/deep.dat") is True
    assert excludes.is_excluded("migrated") is True
    assert excludes.is_excluded("backup/world0.ksd.backup-1") is True
    assert excludes.is_excluded("backup/world0.ksd.backup-9") is True
    assert excludes.is_excluded("world0.ksd") is False
    assert excludes.is_excluded("backup/world0.ksd.backup-0") is False


def test_wildcard_prefix_excludes_subtree() -> None:
    # GIVEN a wildcard directory prefix
    # WHEN checking nested members
    # THEN the whole subtree drops
    excludes = BackupExcludes.from_raw("backup*/**")
    # THEN wildcard prefixes prune the full subtree
    assert excludes.is_excluded("backup1/x") is True
    assert excludes.is_excluded("backup1") is True
    assert excludes.is_excluded("other/x") is False


def test_bare_directory_pattern_excludes_children() -> None:
    # GIVEN a bare directory pattern without a glob suffix
    # WHEN checking nested members
    # THEN children drop for every archive format
    excludes = BackupExcludes.from_raw("migrated")
    assert excludes.is_excluded("migrated/x") is True
    assert excludes.is_excluded("migrated") is True
    assert excludes.is_excluded("world0.ksd") is False


def test_pattern_normalization_trims_slash_prefix() -> None:
    # GIVEN patterns with leading ./ or trailing slashes
    # WHEN parsing the filter
    # THEN they normalize to the same member
    excludes = BackupExcludes.from_raw("./migrated/;migrated/nested/")
    assert excludes.patterns == ("migrated", "migrated/nested")
    assert excludes.is_excluded("migrated/x") is True


def test_blank_filter_disables_all_exclusions() -> None:
    # GIVEN a blank filter value
    # WHEN checking any game-generated path
    # THEN nothing is excluded
    excludes = BackupExcludes.from_raw("  ; ")
    assert excludes.patterns == ()
    assert excludes.is_excluded("migrated/old.dat") is False
    assert excludes.is_excluded("backup/world0.ksd.backup-1") is False


def test_invalid_patterns_warn_and_continue(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN absolute and traversal patterns alongside one valid pattern
    # WHEN parsing the filter
    # THEN the bad entries warn and only the valid one applies
    with caplog.at_level("WARNING", logger="enshctl.backup.excludes"):
        excludes = BackupExcludes.from_raw("/abs;../escape;migrated/**")
    assert excludes.patterns == ("migrated/**",)
    assert any("BACKUP_EXCLUDE" in record.message for record in caplog.records)
    assert excludes.is_excluded("migrated/old.dat") is True
    assert excludes.is_excluded("world0.ksd") is False


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_compress_excludes_default_paths(tmp_path: Path, fmt: BackupFormat) -> None:
    # GIVEN a saves tree with game-generated backup and migrated copies
    saves = _saves_tree(tmp_path)
    archive = tmp_path / f"filtered{fmt.get_extension()}"
    target = tmp_path / "restored"
    target.mkdir()
    excludes = BackupExcludes.from_raw(AppSettings().backup_exclude)
    # WHEN compressing with the default filter
    fmt.compress(saves, archive, 1, excludes=excludes)
    decompress_archive(archive, target)
    # THEN active content round-trips while excluded paths are absent
    assert (target / "world0.ksd").read_bytes() == b"world"
    assert (target / "backup" / "world0.ksd.backup-0").read_bytes() == b"latest"
    assert not (target / "backup" / "world0.ksd.backup-1").exists()
    assert not (target / "backup" / "world0.ksd.backup-9").exists()
    assert not (target / "migrated").exists()


def test_create_backup_logs_excluded_summary(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN saves with excludable copies and default settings
    from enshctl.backup.category import Category

    saves = _saves_tree(tmp_path)
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    plan = BackupPlan.from_settings(settings, saves_dir=saves)
    with caplog.at_level("INFO", logger="enshctl.backup.format"):
        # WHEN creating a backup
        result = create_backup(Category.LIVE, plan, space=SpaceGuard(disk_free=lambda _path: 5 * 1024**3))
    # THEN the archive exists and one summary line reports the exclusions
    assert result is not None
    assert any("BACKUP_EXCLUDE" in record.message for record in caplog.records)
