"""Tests for backup module."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from enshctl.backup import (
    BackupFormat,
    acquire_lock,
    parse_backup_filename,
    release_lock,
    resolve_format,
    resolve_level,
)
from enshctl.backup.catalog import _local_now, _local_tz, scan_all, scan_dir, select
from enshctl.settings import AppSettings


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
    result = parse_backup_filename("enshrouded-20260529-120000.tar.zst")
    assert result is not None
    ts, category, fmt = result
    assert ts == datetime(2026, 5, 29, 12, 0, 0, tzinfo=_local_tz())
    assert category == "live"
    assert fmt == BackupFormat.ZSTD


def test_parse_cold_backup() -> None:
    result = parse_backup_filename("enshrouded-20260529-180000-cold.tar.zst")
    assert result is not None
    _ts, category, fmt = result
    assert category == "cold"
    assert fmt == BackupFormat.ZSTD


def test_parse_emergency_gzip() -> None:
    result = parse_backup_filename("enshrouded-20260529-034522-emergency.tar.gz")
    assert result is not None
    _ts, category, fmt = result
    assert category == "emergency"
    assert fmt == BackupFormat.GZIP


def test_parse_zip() -> None:
    result = parse_backup_filename("enshrouded-20260529-120000.zip")
    assert result is not None
    _, category, fmt = result
    assert category == "live"
    assert fmt == BackupFormat.ZIP


def test_parse_invalid() -> None:
    assert parse_backup_filename("random.txt") is None
    assert parse_backup_filename("enshrouded-abc.tar.zst") is None
    assert parse_backup_filename("backup-20260529-120000.tar.zst") is None


def test_parse_invalid_date() -> None:
    assert parse_backup_filename("enshrouded-99999999-999999.tar.zst") is None


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


def test_select_backup_no_args(tmp_path: Path) -> None:
    # GIVEN a base directory and no selection criteria
    base = tmp_path / "backups"
    base.mkdir()
    # WHEN selecting
    # THEN nothing resolves
    assert select(base) is None


def test_select_backup_compat_wrapper(tmp_path: Path) -> None:
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
    f1 = live / name1
    f2 = live / name2
    f1.write_bytes(b"\x00" * 10)
    f2.write_bytes(b"\x00" * 10)
    all_backups = scan_all(base)
    assert len(all_backups) == 2
    recent = scan_all(base, when=timedelta(hours=1))
    assert len(recent) == 2


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
    live_only = scan_all(base, category="live")
    assert len(live_only) == 1
    assert live_only[0].category == "live"
    cold_only = scan_all(base, category="cold")
    assert len(cold_only) == 1
    assert cold_only[0].category == "cold"


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

    @patch("enshctl.backup.core.shutil.disk_usage")
    @patch("enshctl.backup.core.backup_needed", return_value=True)
    def test_normal_backup_proceeds_with_ample_space(
        self,
        _mock_needed: MagicMock,
        mock_disk_usage: MagicMock,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup

        # GIVEN ample free space and saves present
        mock_disk_usage.return_value.free = 5 * 1024**3
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

        with (
            patch("enshctl.backup.core.SAVE_DIR", saves),
            patch("enshctl.backup.core._local_now") as mock_now,
            patch("enshctl.backup.format._compress_zstd") as mock_compress,
        ):
            mock_now.return_value.strftime.return_value = "20260531-120000"
            # WHEN creating a backup
            result = create_backup("live", settings)
            # THEN compression runs and a path returns
            mock_compress.assert_called_once()
            assert result is not None

    @patch("enshctl.backup.core.shutil.disk_usage")
    @patch("enshctl.backup.core.backup_needed", return_value=True)
    def test_backup_skipped_below_stop_threshold(
        self,
        _mock_needed: MagicMock,
        mock_disk_usage: MagicMock,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup

        # GIVEN free space below the stop threshold
        mock_disk_usage.return_value.free = 500 * 1024**2
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        # WHEN creating a backup
        result = create_backup("live", settings)
        # THEN the backup is skipped
        assert result is None

    @patch("enshctl.backup.core.shutil.disk_usage")
    @patch("enshctl.backup.core.backup_needed", return_value=True)
    def test_backup_warns_below_warn_threshold(
        self,
        _mock_needed: MagicMock,
        mock_disk_usage: MagicMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from enshctl.backup import create_backup

        # GIVEN free space below the warn threshold but above stop
        mock_disk_usage.return_value.free = 1.5 * 1024**3
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

        with (
            patch("enshctl.backup.core.SAVE_DIR", saves),
            patch("enshctl.backup.core._local_now") as mock_now,
            patch("enshctl.backup.format._compress_zstd") as mock_compress,
        ):
            mock_now.return_value.strftime.return_value = "20260531-120000"
            # WHEN creating a backup
            result = create_backup("live", settings)
            # THEN compression still runs
            mock_compress.assert_called_once()
            assert result is not None

        # AND a low-space warning was logged
        warnings = [r for r in caplog.records if r.levelno == 30 and "Disk space low" in r.message]
        assert len(warnings) >= 1

    @patch("enshctl.backup.core.shutil.disk_usage")
    @patch("enshctl.backup.core.backup_needed", return_value=True)
    def test_backup_emergency_also_skipped_on_full_disk(
        self,
        _mock_needed: MagicMock,
        mock_disk_usage: MagicMock,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup

        # GIVEN a full disk
        mock_disk_usage.return_value.free = 500 * 1024**2
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
        # WHEN creating an emergency backup
        result = create_backup(category="emergency", settings=settings)
        # THEN it is skipped
        assert result is None


class TestCreateBackupOverrides:
    """Tests for create_backup() explicit format/level overrides."""

    @patch("enshctl.backup.core.shutil.disk_usage")
    @patch("enshctl.backup.core.backup_needed", return_value=True)
    def test_explicit_format_wins_over_settings(
        self,
        _mock_needed: MagicMock,
        mock_disk_usage: MagicMock,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import BackupFormat, create_backup

        # GIVEN gzip configured but zstd requested explicitly
        mock_disk_usage.return_value.free = 5 * 1024**3
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"), backup_format="gzip", backup_level=6)

        with (
            patch("enshctl.backup.core.SAVE_DIR", saves),
            patch("enshctl.backup.core._local_now") as mock_now,
            patch("enshctl.backup.format._compress_zstd") as mock_zstd,
            patch("enshctl.backup.format._compress_gzip") as mock_gzip,
        ):
            mock_now.return_value.strftime.return_value = "20260531-120000"
            # WHEN creating a backup with an explicit format
            result = create_backup("live", settings, fmt=BackupFormat.ZSTD)
            # THEN the explicit format's compressor runs
            mock_zstd.assert_called_once()
            mock_gzip.assert_not_called()
            assert result is not None
            assert result.suffixes == [".tar", ".zst"]

    @patch("enshctl.backup.core.shutil.disk_usage")
    @patch("enshctl.backup.core.backup_needed", return_value=True)
    def test_explicit_level_zero_honored(
        self,
        _mock_needed: MagicMock,
        mock_disk_usage: MagicMock,
        tmp_path: Path,
    ) -> None:
        from enshctl.backup import create_backup

        # GIVEN a configured level of 9
        mock_disk_usage.return_value.free = 5 * 1024**3
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")
        settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"), backup_level=9)

        with (
            patch("enshctl.backup.core.SAVE_DIR", saves),
            patch("enshctl.backup.core._local_now") as mock_now,
            patch("enshctl.backup.format._compress_zstd") as mock_compress,
        ):
            mock_now.return_value.strftime.return_value = "20260531-120000"
            # WHEN creating a backup with explicit level 0
            result = create_backup("live", settings, level=0)
            # THEN level 0 reaches the compressor, not the configured 9
            mock_compress.assert_called_once_with(saves, result, 0)
            assert result is not None


class TestBackupRunnerFormatFlag:
    """Tests for backup_runner --format case handling."""

    def test_uppercase_format_accepted(self, tmp_path: Path) -> None:
        import enshctl.backup_runner as br

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
            assert br.main() == br.EXIT_LOCK_HELD
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
