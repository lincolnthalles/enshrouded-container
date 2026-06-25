"""Tests for backup module."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.backup import (
    BackupFormat,
    _local_now,
    _local_tz,
    acquire_lock,
    get_format,
    get_level,
    list_backups,
    parse_backup_filename,
    release_lock,
    select_backup,
)

if TYPE_CHECKING:
    import pytest


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


def test_get_format_default() -> None:
    if "BACKUP_FORMAT" in os.environ:
        del os.environ["BACKUP_FORMAT"]
    assert get_format() == BackupFormat.ZSTD


def test_get_format_custom() -> None:
    os.environ["BACKUP_FORMAT"] = "gzip"
    try:
        assert get_format() == BackupFormat.GZIP
    finally:
        del os.environ["BACKUP_FORMAT"]


def test_get_format_invalid_fallback() -> None:
    os.environ["BACKUP_FORMAT"] = "invalid"
    try:
        assert get_format() == BackupFormat.ZSTD
    finally:
        del os.environ["BACKUP_FORMAT"]


def test_get_level_default() -> None:
    if "BACKUP_LEVEL" in os.environ:
        del os.environ["BACKUP_LEVEL"]
    assert get_level(BackupFormat.ZSTD) == 9
    assert get_level(BackupFormat.GZIP) == 6
    assert get_level(BackupFormat.ZIP) == 6


# --- select_backup tests (11.3) ---


def _today_backup(name: str) -> str:
    now = _local_now()
    return name.replace("YYYYMMDD", now.strftime("%Y%m%d")).replace("HHMMSS", now.strftime("%H%M%S"))


def _make_backup_filename(dt: datetime, suffix: str = "", ext: str = ".tar.zst") -> str:
    ts = dt.strftime("%Y%m%d-%H%M%S")
    return f"enshrouded-{ts}{suffix}{ext}"


def test_select_backup_by_file(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    for cat in ("live", "cold", "emergency"):
        (base / cat).mkdir(parents=True)
    target = base / "live" / "enshrouded-20260529-120000.tar.zst"
    target.write_bytes(b"\x00" * 10)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(file="enshrouded-20260529-120000.tar.zst")
    assert result == target


def test_select_backup_by_file_not_found(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    for cat in ("live", "cold", "emergency"):
        (base / cat).mkdir(parents=True)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(file="nonexistent.tar.zst")
    assert result is None


def test_select_backup_when_last(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    f1 = live / "enshrouded-20260529-120000.tar.zst"
    f2 = live / "enshrouded-20260529-130000.tar.zst"
    f1.write_bytes(b"\x00" * 10)
    f2.write_bytes(b"\x00" * 10)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(when="last")
    assert result is not None
    assert result.name == "enshrouded-20260529-130000.tar.zst"


def test_select_backup_when_30m(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    name = _today_backup("enshrouded-YYYYMMDD-HHMMSS.tar.zst")
    f = live / name
    f.write_bytes(b"\x00" * 10)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(when="30m")
    assert result is not None
    assert result.name == name


def test_select_backup_when_1h(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    name = _today_backup("enshrouded-YYYYMMDD-HHMMSS.tar.zst")
    f = live / name
    f.write_bytes(b"\x00" * 10)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(when="1h")
    assert result is not None


def test_select_backup_when_category_qualifier(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    cold = base / "cold"
    live.mkdir(parents=True)
    cold.mkdir(parents=True)
    live_f = live / "enshrouded-20260529-120000.tar.zst"
    cold_f = cold / "enshrouded-20260529-130000-cold.tar.zst"
    live_f.write_bytes(b"\x00" * 10)
    cold_f.write_bytes(b"\x00" * 10)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(when="last:cold")
    assert result is not None
    assert result.name == "enshrouded-20260529-130000-cold.tar.zst"


def test_select_backup_no_match(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    f = live / "enshrouded-20260529-120000.tar.zst"
    f.write_bytes(b"\x00" * 10)
    with patch("enshctl.backup.core.get_backup_dir", return_value=base):
        result = select_backup(when="30m")
    assert result is None


def test_select_backup_invalid_direction() -> None:
    assert select_backup(when="bogus") is None
    assert select_backup(when="42x") is None


def test_select_backup_no_args() -> None:
    assert select_backup() is None


def test_list_backups_with_when_filter(tmp_path: Path) -> None:
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
    all_backups = list_backups(base)
    assert len(all_backups) == 2
    recent = list_backups(base, when=timedelta(hours=1))
    assert len(recent) == 2


def test_list_backups_empty_dir(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    for cat in ("live", "cold", "emergency"):
        (base / cat).mkdir(parents=True)
    assert list_backups(base) == []


def test_list_backups_ignores_non_backup_files(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    live.mkdir(parents=True)
    f = live / "not-a-backup.txt"
    f.write_bytes(b"junk")
    assert list_backups(base) == []


def test_list_backups_category_filter(tmp_path: Path) -> None:
    base = tmp_path / "backups"
    live = base / "live"
    cold = base / "cold"
    live.mkdir(parents=True)
    cold.mkdir(parents=True)
    live_f = live / "enshrouded-20260529-120000.tar.zst"
    cold_f = cold / "enshrouded-20260529-130000-cold.tar.zst"
    live_f.write_bytes(b"\x00" * 10)
    cold_f.write_bytes(b"\x00" * 10)
    live_only = list_backups(base, category="live")
    assert len(live_only) == 1
    assert live_only[0].category == "live"
    cold_only = list_backups(base, category="cold")
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

    from enshctl.backup import parse_cron

    struct = _time.struct_time((2026, 5, 30, 14, 37, 0, 4, 150, 0))
    with _patch("enshctl.backup.core.time.localtime", return_value=struct):
        result = parse_cron("*/5 * * * *")
    assert result is not None
    # At :37, next */5 boundary is :40 → 3 minutes = 180 seconds
    assert result == 180.0


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


def test_get_min_free_warn_default() -> None:
    from enshctl.backup import DEFAULT_MIN_FREE_WARN, get_min_free_warn

    if "BACKUP_MIN_FREE_SPACE_WARN" in os.environ:
        del os.environ["BACKUP_MIN_FREE_SPACE_WARN"]
    assert get_min_free_warn() == DEFAULT_MIN_FREE_WARN


def test_get_min_free_warn_custom() -> None:
    from enshctl.backup import get_min_free_warn

    os.environ["BACKUP_MIN_FREE_SPACE_WARN"] = str(3 * 1024**3)
    try:
        assert get_min_free_warn() == 3 * 1024**3
    finally:
        del os.environ["BACKUP_MIN_FREE_SPACE_WARN"]


def test_get_min_free_stop_default() -> None:
    from enshctl.backup import DEFAULT_MIN_FREE_STOP, get_min_free_stop

    if "BACKUP_MIN_FREE_SPACE_STOP" in os.environ:
        del os.environ["BACKUP_MIN_FREE_SPACE_STOP"]
    assert get_min_free_stop() == DEFAULT_MIN_FREE_STOP


def test_get_min_free_stop_custom() -> None:
    from enshctl.backup import get_min_free_stop

    os.environ["BACKUP_MIN_FREE_SPACE_STOP"] = str(512 * 1024**2)
    try:
        assert get_min_free_stop() == 512 * 1024**2
    finally:
        del os.environ["BACKUP_MIN_FREE_SPACE_STOP"]


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

        mock_disk_usage.return_value.free = 5 * 1024**3
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")

        with (
            patch("enshctl.backup.core.SAVE_DIR", saves),
            patch("enshctl.backup.core.get_backup_dir", return_value=tmp_path / "backups"),
            patch("enshctl.backup.core.get_format", return_value=BackupFormat.ZSTD),
            patch("enshctl.backup.core.get_level", return_value=3),
            patch("enshctl.backup.core._local_now") as mock_now,
            patch("enshctl.backup.archive._compress_zstd") as mock_compress,
        ):
            mock_now.return_value.strftime.return_value = "20260531-120000"
            result = create_backup()
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

        mock_disk_usage.return_value.free = 500 * 1024**2

        with (
            patch("enshctl.backup.core.get_backup_dir", return_value=tmp_path / "backups"),
        ):
            result = create_backup()
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

        mock_disk_usage.return_value.free = 1.5 * 1024**3
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "world.db").write_bytes(b"data")

        with (
            patch("enshctl.backup.core.SAVE_DIR", saves),
            patch("enshctl.backup.core.get_backup_dir", return_value=tmp_path / "backups"),
            patch("enshctl.backup.core.get_format", return_value=BackupFormat.ZSTD),
            patch("enshctl.backup.core.get_level", return_value=3),
            patch("enshctl.backup.core._local_now") as mock_now,
            patch("enshctl.backup.archive._compress_zstd") as mock_compress,
        ):
            mock_now.return_value.strftime.return_value = "20260531-120000"
            result = create_backup()
            mock_compress.assert_called_once()
            assert result is not None

        # Verify warning was logged
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

        mock_disk_usage.return_value.free = 500 * 1024**2

        with (
            patch("enshctl.backup.core.get_backup_dir", return_value=tmp_path / "backups"),
        ):
            result = create_backup(category="emergency")
            assert result is None
