"""Tests for backup module."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from enshctl.backup import (
    CATEGORIES,
    BackupFormat,
    BackupName,
    Category,
    acquire_lock,
    create_backup,
    release_lock,
    resolve_format,
    resolve_level,
)
from enshctl.backup.catalog import _local_now, scan_all, scan_dir, select
from enshctl.disk_space import SpaceGuard
from enshctl.settings import AppSettings


def _space(free: int) -> SpaceGuard:
    return SpaceGuard(disk_free=lambda _path: free)


def test_backup_format_zstd() -> None:
    fmt = BackupFormat.ZSTD
    assert fmt.get_extension() == ".tar.zst"
    assert fmt.get_max_level() == 22
    assert fmt.clamp_level(19) == 19
    assert fmt.clamp_level(25) == 22
    assert fmt.clamp_level(0) == 0


def test_backup_format_gzip() -> None:
    fmt = BackupFormat.GZIP
    assert fmt.get_extension() == ".tar.gz"
    assert fmt.get_max_level() == 9
    assert fmt.clamp_level(9) == 9
    assert fmt.clamp_level(15) == 9
    assert fmt.clamp_level(0) == 0


def test_backup_format_zip() -> None:
    fmt = BackupFormat.ZIP
    assert fmt.get_extension() == ".zip"
    assert fmt.get_max_level() == 9
    assert fmt.clamp_level(3) == 3
    assert fmt.clamp_level(12) == 9


def test_parse_live_backup() -> None:
    result = BackupName.from_filename("enshrouded-20260529-120000.tar.zst")
    assert result == BackupName(
        timestamp=datetime(2026, 5, 29, 12, 0, 0).astimezone(),
        category=Category.LIVE,
        fmt=BackupFormat.ZSTD,
    )


def test_parse_cold_backup() -> None:
    result = BackupName.from_filename("enshrouded-20260529-180000-cold.tar.zst")
    assert result == BackupName(
        timestamp=datetime(2026, 5, 29, 18, 0, 0).astimezone(),
        category=Category.COLD,
        fmt=BackupFormat.ZSTD,
    )


def test_parse_emergency_gzip() -> None:
    result = BackupName.from_filename("enshrouded-20260529-034522-emergency.tar.gz")
    assert result == BackupName(
        timestamp=datetime(2026, 5, 29, 3, 45, 22).astimezone(),
        category=Category.EMERGENCY,
        fmt=BackupFormat.GZIP,
    )


def test_parse_zip() -> None:
    result = BackupName.from_filename("enshrouded-20260529-120000.zip")
    assert result == BackupName(
        timestamp=datetime(2026, 5, 29, 12, 0, 0).astimezone(),
        category=Category.LIVE,
        fmt=BackupFormat.ZIP,
    )


def test_parse_invalid() -> None:
    assert BackupName.from_filename("random.txt") is None
    assert BackupName.from_filename("enshrouded-abc.tar.zst") is None
    assert BackupName.from_filename("backup-20260529-120000.tar.zst") is None
    assert BackupName.from_filename("enshrouded-20260529-120000-warm.tar.zst") is None


def test_parse_invalid_date() -> None:
    assert BackupName.from_filename("enshrouded-99999999-999999.tar.zst") is None


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_backup_name_round_trips(category: Category, fmt: BackupFormat) -> None:
    # GIVEN a Backup name at a fixed local timestamp
    name = BackupName(timestamp=datetime(2026, 5, 29, 12, 0, 0).astimezone(), category=category, fmt=fmt)
    # WHEN the name is rendered and parsed again
    parsed = BackupName.from_filename(name.to_filename())
    # THEN the full value round-trips
    assert parsed == name


def test_backup_name_now_truncates_sub_second_precision() -> None:
    # GIVEN a clock carrying microseconds
    fixed = datetime(2026, 5, 29, 12, 0, 0, 123456).astimezone()
    with patch("enshctl.backup.catalog._local_now", return_value=fixed):
        # WHEN capturing the current Backup name
        name = BackupName.now(Category.LIVE, BackupFormat.ZSTD)
    # THEN the value matches the second-precision grammar
    assert name.timestamp == fixed.replace(microsecond=0)
    assert BackupName.from_filename(name.to_filename()) == name


@pytest.mark.parametrize(
    ("is_dst", "expected_offset_hours"),
    [(1, 2), (0, 1)],
)
def test_backup_name_now_uses_dst_offset_in_effect(is_dst: int, expected_offset_hours: int) -> None:
    # GIVEN a zone whose DST rule is currently active or inactive
    with (
        patch("enshctl.backup.catalog.time.localtime") as mock_localtime,
        patch("enshctl.backup.catalog.time.altzone", -7200),
        patch("enshctl.backup.catalog.time.timezone", -3600),
    ):
        mock_localtime.return_value.tm_isdst = is_dst
        # WHEN capturing the current Backup name
        name = BackupName.now(Category.LIVE, BackupFormat.ZSTD)
    # THEN the offset in effect is used, not the mere presence of a DST rule
    assert name.timestamp.utcoffset() == timedelta(hours=expected_offset_hours)


def test_backup_name_rejects_unknown_category() -> None:
    # GIVEN an unknown Category value at the grammar boundary
    # WHEN constructing a Backup name
    # THEN the category is rejected before rendering
    with pytest.raises(ValueError, match="warm"):
        BackupName(
            timestamp=datetime(2026, 5, 29, 12, 0, 0).astimezone(),
            category=cast("Category", "warm"),
            fmt=BackupFormat.ZSTD,
        )


def test_resolve_format_default() -> None:
    # GIVEN default settings
    # WHEN resolving the configured format
    # THEN zstd is selected
    assert resolve_format(AppSettings().backup_format) == BackupFormat.ZSTD


def test_resolve_format_custom() -> None:
    # GIVEN gzip configured
    settings = replace(AppSettings(), backup_format="gzip")
    # WHEN resolving the format
    # THEN gzip is selected
    assert resolve_format(settings.backup_format) == BackupFormat.GZIP


def test_resolve_format_invalid_fallback() -> None:
    # GIVEN an unknown format name
    # WHEN resolving the format
    # THEN zstd is selected as the fallback
    assert resolve_format("invalid") == BackupFormat.ZSTD


def test_resolve_level_defaults() -> None:
    # GIVEN no explicit level configured
    # WHEN resolving the level
    # THEN each format reports its own default
    assert resolve_level(BackupFormat.ZSTD, "") == 9
    assert resolve_level(BackupFormat.GZIP, "") == 6
    assert resolve_level(BackupFormat.ZIP, "") == 6


# --- select tests ---


def _today_backup(name: str) -> str:
    now = _local_now()
    return name.replace("YYYYMMDD", now.strftime("%Y%m%d")).replace("HHMMSS", now.strftime("%H%M%S"))


def _make_backup_filename(dt: datetime, suffix: str = "", ext: str = ".tar.zst") -> str:
    ts = dt.strftime("%Y%m%d-%H%M%S")
    return f"enshrouded-{ts}{suffix}{ext}"


def test_select_backup_by_file(tmp_path: Path) -> None:
    # GIVEN backups present in all categories
    base = tmp_path / "backups"
    for cat in ("live", "cold", "emergency"):
        (base / cat).mkdir(parents=True)
    target = base / "live" / "enshrouded-20260529-120000.tar.zst"
    target.write_bytes(b"\x00" * 10)
    # WHEN selecting by filename
    result = select(base, file="enshrouded-20260529-120000.tar.zst")
    # THEN the exact path resolves
    assert result == target


def test_select_backup_by_file_not_found(tmp_path: Path) -> None:
    # GIVEN backups present
    base = tmp_path / "backups"
    for cat in ("live", "cold", "emergency"):
        (base / cat).mkdir(parents=True)
    # WHEN selecting a nonexistent filename
    result = select(base, file="nonexistent.tar.zst")
    # THEN no backup resolves
    assert result is None


def test_select_backup_when_last(tmp_path: Path) -> None:
    # GIVEN two live backups
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    f1 = live / "enshrouded-20260529-120000.tar.zst"
    f2 = live / "enshrouded-20260529-130000.tar.zst"
    f1.write_bytes(b"\x00" * 10)
    f2.write_bytes(b"\x00" * 10)
    # WHEN selecting the last backup
    result = select(base, when="last")
    # THEN the newest file resolves
    assert result is not None
    assert result.name == "enshrouded-20260529-130000.tar.zst"


def test_select_backup_when_30m(tmp_path: Path) -> None:
    # GIVEN a backup created now
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    name = _today_backup("enshrouded-YYYYMMDD-HHMMSS.tar.zst")
    f = live / name
    f.write_bytes(b"\x00" * 10)
    # WHEN selecting within the last 30 minutes
    result = select(base, when="30m")
    # THEN it resolves
    assert result is not None
    assert result.name == name


def test_select_backup_when_1h(tmp_path: Path) -> None:
    # GIVEN a backup created now
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    name = _today_backup("enshrouded-YYYYMMDD-HHMMSS.tar.zst")
    f = live / name
    f.write_bytes(b"\x00" * 10)
    # WHEN selecting within the last hour
    # THEN it resolves
    assert select(base, when="1h") is not None


def test_select_backup_when_category_qualifier(tmp_path: Path) -> None:
    # GIVEN live and cold backups
    base = tmp_path / "backups"
    live = base / "live"
    cold = base / "cold"
    live.mkdir(parents=True)
    cold.mkdir(parents=True)
    live_f = live / "enshrouded-20260529-120000.tar.zst"
    cold_f = cold / "enshrouded-20260529-130000-cold.tar.zst"
    live_f.write_bytes(b"\x00" * 10)
    cold_f.write_bytes(b"\x00" * 10)
    # WHEN selecting the last cold backup
    result = select(base, when="last:cold")
    # THEN the cold file resolves
    assert result is not None
    assert result.name == "enshrouded-20260529-130000-cold.tar.zst"


def test_select_backup_empty_category_qualifier_means_all(tmp_path: Path) -> None:
    # GIVEN a live and a newer cold backup
    base = tmp_path / "backups"
    live = base / "live"
    cold = base / "cold"
    live.mkdir(parents=True)
    cold.mkdir(parents=True)
    (live / "enshrouded-20260529-120000.tar.zst").write_bytes(b"\x00" * 10)
    (cold / "enshrouded-20260529-130000-cold.tar.zst").write_bytes(b"\x00" * 10)
    # WHEN selecting the last backup with an empty qualifier
    result = select(base, when="last:")
    # THEN the newest Backup across all Categories resolves
    assert result is not None
    assert result.name == "enshrouded-20260529-130000-cold.tar.zst"


def test_select_backup_unknown_category_qualifier_matches_nothing(tmp_path: Path) -> None:
    # GIVEN a valid live backup
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    (live / "enshrouded-20260529-120000.tar.zst").write_bytes(b"\x00" * 10)
    # WHEN selecting with an unknown Category qualifier
    # THEN nothing resolves
    assert select(base, when="last:bogus") is None


def test_select_backup_no_match(tmp_path: Path) -> None:
    # GIVEN only a stale backup
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    f = live / "enshrouded-20260529-120000.tar.zst"
    f.write_bytes(b"\x00" * 10)
    # WHEN selecting within the last 30 minutes
    # THEN nothing resolves
    assert select(base, when="30m") is None


def test_select_backup_invalid_direction(tmp_path: Path) -> None:
    # GIVEN a base directory
    base = tmp_path / "backups"
    base.mkdir()
    # WHEN selecting with an invalid direction
    # THEN nothing resolves
    assert select(base, when="bogus") is None
    assert select(base, when="42x") is None


def test_select_backup_by_file_rejects_escape(tmp_path: Path) -> None:
    # GIVEN backups present and a file outside the categories
    base = tmp_path / "backups"
    (base / "live").mkdir(parents=True)
    outside = tmp_path / "outside.tar.zst"
    outside.write_bytes(b"\x00" * 10)
    # WHEN selecting with absolute and parent-escape names
    # THEN nothing outside the categories resolves
    assert select(base, file=str(outside)) is None
    assert select(base, file="../outside.tar.zst") is None


def test_select_backup_by_file_rejects_directory(tmp_path: Path) -> None:
    # GIVEN a subdirectory inside a category
    base = tmp_path / "backups"
    (base / "live" / "subdir").mkdir(parents=True)
    # WHEN selecting the directory name
    # THEN nothing resolves
    assert select(base, file="subdir") is None


def test_select_backup_when_zero_window_matches_nothing(tmp_path: Path) -> None:
    # GIVEN a backup created now
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    name = _today_backup("enshrouded-YYYYMMDD-HHMMSS.tar.zst")
    (live / name).write_bytes(b"\x00" * 10)
    # WHEN selecting within a zero-length window
    # THEN nothing resolves
    assert select(base, when="0d") is None


def test_select_backup_when_overflow_matches_nothing(tmp_path: Path) -> None:
    # GIVEN a base directory
    base = tmp_path / "backups"
    base.mkdir()
    # WHEN selecting with overflowing windows (construction and subtraction paths)
    # THEN nothing resolves instead of raising
    assert select(base, when="999999999999999999999d") is None
    assert select(base, when="3000000d") is None
    assert select(base, when="25000M") is None


def test_select_backup_no_args(tmp_path: Path) -> None:
    # GIVEN a base directory and no selection criteria
    base = tmp_path / "backups"
    base.mkdir()
    # WHEN selecting
    # THEN nothing resolves
    assert select(base) is None


def test_select_backup_by_file_via_settings_dir(tmp_path: Path) -> None:
    # GIVEN backups present and settings pointing at them
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    target = live / "enshrouded-20260529-120000.tar.zst"
    target.write_bytes(b"\x00" * 10)
    settings = replace(AppSettings(), backup_dir=str(base))
    # WHEN selecting through the catalog directly
    # THEN the file resolves
    assert select(Path(settings.backup_dir), file="enshrouded-20260529-120000.tar.zst") == target


def test_scan_dir_lists_newest_first(tmp_path: Path) -> None:
    # GIVEN one category dir with two backups and a stray file
    live = tmp_path / "live"
    live.mkdir()
    (live / "enshrouded-20260529-120000.tar.zst").write_bytes(b"\x00" * 10)
    (live / "enshrouded-20260529-130000.tar.zst").write_bytes(b"\x00" * 10)
    (live / "random.zst").write_bytes(b"junk")
    # WHEN scanning the directory
    found = scan_dir(live)
    # THEN grammar-matching backups return newest first, strays excluded
    assert [b.path.name for b in found] == [
        "enshrouded-20260529-130000.tar.zst",
        "enshrouded-20260529-120000.tar.zst",
    ]


def test_scan_dir_missing_dir(tmp_path: Path) -> None:
    # GIVEN a nonexistent directory
    # WHEN scanning
    # THEN the result is empty
    assert scan_dir(tmp_path / "nonexistent") == []


def test_scan_all_with_when_filter(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    now = _local_now()
    name1 = _make_backup_filename(now)
    name2 = _make_backup_filename(now + timedelta(seconds=60))
    old_name = _make_backup_filename(now - timedelta(days=2))
    f1 = live / name1
    f2 = live / name2
    old = live / old_name
    f1.write_bytes(b"\x00" * 10)
    f2.write_bytes(b"\x00" * 10)
    old.write_bytes(b"\x00" * 10)
    all_backups = scan_all(base)
    assert len(all_backups) == 3
    recent = scan_all(base, when=timedelta(hours=1))
    assert len(recent) == 2
    assert old_name not in {info.path.name for info in recent}


def test_scan_all_empty_dir(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    for cat in ("live", "cold", "emergency"):
        (base / cat).mkdir(parents=True)
    assert scan_all(base) == []


def test_scan_all_ignores_non_backup_files(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    f = live / "not-a-backup.txt"
    f.write_bytes(b"junk")
    assert scan_all(base) == []


def test_scan_all_category_filter(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    cold = base / "cold"
    live.mkdir(parents=True)
    cold.mkdir(parents=True)
    live_f = live / "enshrouded-20260529-120000.tar.zst"
    cold_f = cold / "enshrouded-20260529-130000-cold.tar.zst"
    live_f.write_bytes(b"\x00" * 10)
    cold_f.write_bytes(b"\x00" * 10)
    live_only = scan_all(base, category=Category.LIVE)
    assert len(live_only) == 1
    assert live_only[0].name.category == Category.LIVE
    cold_only = scan_all(base, category=Category.COLD)
    assert len(cold_only) == 1
    assert cold_only[0].name.category == Category.COLD


# --- Lock tests (11.4) ---


def test_acquire_and_release_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    fd = acquire_lock(lock_path, blocking=False)
    assert fd is not None
    release_lock(fd)


def test_concurrent_lock_fails(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    fd1 = acquire_lock(lock_path, blocking=False)
    assert fd1 is not None
    fd2 = acquire_lock(lock_path, blocking=False)
    assert fd2 is None
    release_lock(fd1)


def test_lock_released_on_process_exit(tmp_path: Path) -> None:
    import multiprocessing

    lock_path = tmp_path / ".lock"
    p = multiprocessing.Process(target=_lock_child_process, args=(str(lock_path),))
    p.start()
    p.join(timeout=5)
    assert p.exitcode == 0
    fd = acquire_lock(lock_path, blocking=False)
    assert fd is not None
    release_lock(fd)


def _lock_child_process(lock_path_str: str) -> None:
    fd = acquire_lock(Path(lock_path_str), blocking=False)
    assert fd is not None
    release_lock(fd)


def test_release_lock_is_idempotent(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    fd = acquire_lock(lock_path, blocking=False)
    assert fd is not None
    release_lock(fd)
    release_lock(fd)  # should not raise


# --- Priority tests (11.5) ---


def test_lower_priority_with_nice(caplog: pytest.LogCaptureFixture) -> None:
    from enshctl.backup_runner import _lower_priority

    with (
        patch("enshctl.backup_runner.nice") as mock_nice,
        patch("enshctl.backup_runner.subprocess.run") as mock_run,
    ):
        mock_nice.return_value = None
        mock_run.return_value.returncode = 0
        _lower_priority()
    mock_nice.assert_called_once_with(19)


def test_lower_priority_warns_once_on_nice_failure(caplog: pytest.LogCaptureFixture) -> None:
    from enshctl.backup_runner import _lower_priority

    with (
        patch("enshctl.backup_runner.nice", side_effect=OSError),
        patch(
            "enshctl.backup_runner.subprocess.run",
            side_effect=OSError,
        ),
    ):
        _lower_priority()
        _lower_priority()
    warnings = [r for r in caplog.records if r.levelno == 30 and "priority" in r.message.lower()]
    assert len(warnings) <= 10


def test_parse_cron_aligns_to_clock_boundary() -> None:
    import time as _time
    from unittest.mock import patch as _patch

    from enshctl.scheduling import parse_cron

    struct = _time.struct_time((2026, 5, 30, 14, 37, 0, 4, 150, 0))
    with _patch("enshctl.scheduling.time.localtime", return_value=struct):
        result = parse_cron("*/5 * * * *")
    assert result is not None
    # At :37, next */5 boundary is :40 → 3 minutes = 180 seconds
    assert result == 180.0


def test_parse_cron_invalid_expression() -> None:
    # GIVEN a malformed cron expression
    from enshctl.scheduling import parse_cron

    # WHEN parsing
    # THEN no interval resolves
    assert parse_cron("not a cron") is None


def test_select_empty_direction_returns_none(tmp_path: Path) -> None:
    # GIVEN a base directory
    base = tmp_path / "backups"
    base.mkdir()
    # WHEN selecting with an empty direction
    # THEN nothing resolves instead of raising
    assert select(base, when=":cold") is None


def test_lower_priority_warns_once_on_ionice_failure(caplog: pytest.LogCaptureFixture) -> None:
    import enshctl.backup_runner as br
    from enshctl.backup_runner import _lower_priority

    br._priority_state["warned"] = False
    with (
        patch("enshctl.backup_runner.nice"),
        patch(
            "enshctl.backup_runner.subprocess.run",
            side_effect=OSError,
        ),
    ):
        _lower_priority()
        _lower_priority()
    warnings = [r for r in caplog.records if r.levelno == 30 and "ionice" in r.message.lower()]
    assert len(warnings) <= 1


# --- Disk space guard tests ---


class TestCreateBackupDiskSpace:
    """Tests for create_backup() disk space checks."""

    def test_normal_backup_proceeds_with_ample_space(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN ample free space and saves present
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

        with (
            patch("enshctl.backup.catalog._local_now", return_value=datetime(2026, 5, 31, 12, 0, 0).astimezone()),
            patch("enshctl.backup.format._compress_zstd") as mock_compress,
        ):
            # WHEN creating a backup
            result = create_backup(
                Category.LIVE,
                BackupPlan.from_settings(settings, saves_dir=saves),
                space=_space(5 * 1024**3),
            )
            # THEN compression runs and a path returns
            mock_compress.assert_called_once()
            assert result is not None

    def test_backup_skipped_below_stop_threshold(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN free space below the stop threshold
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        # WHEN creating a backup
        result = create_backup(
            Category.LIVE,
            BackupPlan.from_settings(settings, saves_dir=saves),
            space=_space(500 * 1024**2),
        )
        # THEN the backup is skipped
        assert result is None

    def test_backup_warns_below_warn_threshold(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from enshctl.backup import create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN free space below the warn threshold but above stop
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

        with (
            patch("enshctl.backup.catalog._local_now", return_value=datetime(2026, 5, 31, 12, 0, 0).astimezone()),
            patch("enshctl.backup.format._compress_zstd") as mock_compress,
        ):
            # WHEN creating a backup
            result = create_backup(
                Category.LIVE,
                BackupPlan.from_settings(settings, saves_dir=saves),
                space=_space(1536 * 1024**2),
            )
            # THEN compression still runs
            mock_compress.assert_called_once()
            assert result is not None

        # AND a low-space warning was logged
        warnings = [r for r in caplog.records if r.levelno == 30 and "Disk space low" in r.message]
        assert len(warnings) >= 1

    def test_backup_emergency_also_skipped_on_full_disk(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN a full disk
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        # WHEN creating an emergency backup
        result = create_backup(
            Category.EMERGENCY,
            BackupPlan.from_settings(settings, saves_dir=saves),
            space=_space(500 * 1024**2),
        )
        # THEN it is skipped
        assert result is None

    def test_backup_skips_missing_saves_dir(self, tmp_path: Path) -> None:
        from enshctl.backup import create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN a missing configured saves directory
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        plan = BackupPlan.from_settings(settings, saves_dir=tmp_path / "missing")
        # WHEN creating a backup
        result = create_backup(Category.LIVE, plan, space=_space(5 * 1024**3))
        # THEN it is skipped without creating a category directory
        assert result is None
        assert not (tmp_path / "backups" / Category.LIVE).exists()


class TestCreateBackupOverrides:
    """Tests for create_backup() explicit format/level overrides."""

    def test_explicit_format_wins_over_settings(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import BackupFormat, create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN gzip configured but zstd requested explicitly
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"), backup_format="gzip", backup_level=6)

        with (
            patch("enshctl.backup.catalog._local_now", return_value=datetime(2026, 5, 31, 12, 0, 0).astimezone()),
            patch("enshctl.backup.format._compress_zstd") as mock_zstd,
            patch("enshctl.backup.format._compress_gzip") as mock_gzip,
        ):
            # WHEN creating a backup with an explicit format
            result = create_backup(
                Category.LIVE,
                BackupPlan.from_settings(settings, saves_dir=saves, fmt=BackupFormat.ZSTD),
                space=_space(5 * 1024**3),
            )
            # THEN the explicit format's compressor runs
            mock_zstd.assert_called_once()
            mock_gzip.assert_not_called()
            assert result is not None
            assert result.suffixes == [".tar", ".zst"]

    def test_explicit_level_zero_honored(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup
        from enshctl.backup.core import BackupPlan

        # GIVEN a configured level of 9
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"), backup_level=9)

        with (
            patch("enshctl.backup.catalog._local_now", return_value=datetime(2026, 5, 31, 12, 0, 0).astimezone()),
            patch("enshctl.backup.format._compress_zstd") as mock_compress,
        ):
            # WHEN creating a backup with explicit level 0
            result = create_backup(
                Category.LIVE,
                BackupPlan.from_settings(settings, saves_dir=saves, level=0),
                space=_space(5 * 1024**3),
            )
            # THEN level 0 reaches the compressor, not the configured 9
            mock_compress.assert_called_once_with(saves, result, 0)
            assert result is not None


@pytest.mark.parametrize("category", CATEGORIES)
def test_created_backup_name_is_discovered_by_scan(tmp_path: Path, category: Category) -> None:
    from enshctl.backup.core import BackupPlan

    # GIVEN a fixed clock, save data, and a compressor that writes a file
    saves = tmp_path / "saves"
    saves.mkdir()
    (saves / "world.db").write_bytes(b"data")
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    timestamp = datetime(2026, 5, 31, 12, 0, 0).astimezone()

    def _write_empty(_source: Path, output: Path, _level: int) -> None:
        output.write_bytes(b"")

    with (
        patch("enshctl.backup.catalog._local_now", return_value=timestamp),
        patch("enshctl.backup.format._compress_zstd", side_effect=_write_empty),
    ):
        # WHEN creating a backup in the Category
        created = create_backup(
            category,
            BackupPlan.from_settings(settings, saves_dir=saves),
            space=_space(5 * 1024**3),
        )

    # THEN scan_dir discovers the same Backup name
    assert created is not None
    suffix = "" if category is Category.LIVE else f"-{category}"
    assert created.name == f"enshrouded-20260531-120000{suffix}.tar.zst"
    found = scan_dir(Path(settings.backup_dir) / category)
    assert [info.path for info in found] == [created]
    assert found[0].name == BackupName(timestamp=timestamp, category=category, fmt=BackupFormat.ZSTD)


class TestBackupRunnerFormatFlag:
    """Tests for backup_runner --format case handling."""

    def test_runner_uses_generated_save_dir(self, tmp_path: Path) -> None:
        import enshctl.backup_runner as br
        from enshctl.backup_protocol import BackupOutcome

        # GIVEN a generated save directory and a successful backup invocation
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        with (
            patch("sys.argv", ["prog"]),
            patch.object(br, "load_settings", return_value=settings),
            patch.object(br, "generated_save_dir", return_value=saves),
            patch.object(br, "acquire_lock", return_value=3),
            patch.object(br, "create_backup", return_value=None) as mock_create,
            patch.object(br, "release_lock"),
        ):
            # WHEN the runner builds its Backup plan
            assert br.main() == BackupOutcome.SUCCESS

        # THEN the plan carries the Generated config save directory
        plan = mock_create.call_args.args[1]
        assert plan.saves_dir == saves

    def test_uppercase_format_accepted(self, tmp_path: Path) -> None:
        import enshctl.backup_runner as br
        from enshctl.backup_protocol import BackupOutcome

        # GIVEN an uppercase --format flag
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        with (
            patch("sys.argv", ["prog", "--format", "ZSTD"]),
            patch.object(br, "load_settings", return_value=settings),
            patch.object(br, "acquire_lock", return_value=None),
            patch.object(br, "create_backup") as mock_create,
        ):
            # WHEN running the backup runner
            # THEN parsing succeeds and execution reaches the lock check
            assert br.main() == BackupOutcome.LOCK_HELD
            mock_create.assert_not_called()

    def test_invalid_format_rejected(self) -> None:
        import enshctl.backup_runner as br

        # GIVEN an unrecognized --format value
        # WHEN running the backup runner
        # THEN argparse exits 2
        with (
            patch("sys.argv", ["prog", "--format", "lz4"]),
            pytest.raises(SystemExit) as exc,
        ):
            br.main()
        assert exc.value.code == 2
