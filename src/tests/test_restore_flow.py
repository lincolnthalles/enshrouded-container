"""Tests for the restore transaction through injected system seams."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.config import SaveDirectories
from enshctl.restore import RestoreError
from enshctl.restore_flow import RestoreIO, RestoreOutcome, restore_transaction
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from enshctl.disk_space import SpaceGuard


class FakeLock:
    def __init__(self, fd: int | None = 3) -> None:
        self._fd = fd
        self.acquired: list[tuple[Path, int]] = []
        self.released: list[int] = []

    def acquire(self, path: Path, wait_seconds: int = 0) -> int | None:
        self.acquired.append((path, wait_seconds))
        return self._fd

    def release(self, fd: int) -> None:
        self.released.append(fd)


class RecordingRestore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Path, Path, Path, SpaceGuard]] = []

    def __call__(
        self,
        backup_path: Path,
        *,
        saves_dir: Path,
        tmp_dir: Path,
        space: SpaceGuard,
    ) -> None:
        self.calls.append((backup_path, saves_dir, tmp_dir, space))
        if self.error is not None:
            raise self.error


def test_restore_transaction_locks_restores_and_releases(tmp_path: Path) -> None:
    # GIVEN a selected Backup, resolved Save directories, and injected effects
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    backup = tmp_path / "backups" / "enshrouded-20260529-120000.tar.zst"
    save_directories = SaveDirectories(tmp_path / "saves")
    lock = FakeLock()
    restore = RecordingRestore()
    io = RestoreIO(lock=lock, restore=restore)

    # WHEN running the restore transaction
    outcome = restore_transaction(backup, Path(settings.backup_dir), save_directories, restore_io=io)

    # THEN it holds the lock, restores, and releases
    assert outcome is RestoreOutcome.SUCCESS
    assert lock.acquired == [(tmp_path / "backups" / ".lock", 0)]
    assert lock.released == [3]
    assert restore.calls == [(backup, save_directories.saves_dir, save_directories.restore_tmp_dir, io.space_guard)]


def test_restore_transaction_reports_lock_held(tmp_path: Path) -> None:
    # GIVEN the backup lock held by another process
    settings = AppSettings()
    lock = FakeLock(fd=None)
    restore = RecordingRestore()
    io = RestoreIO(lock=lock, restore=restore)

    # WHEN running the restore transaction
    outcome = restore_transaction(
        tmp_path / "backups" / "enshrouded-20260529-120000.tar.zst",
        Path(settings.backup_dir),
        SaveDirectories(tmp_path / "saves"),
        restore_io=io,
    )

    # THEN it reports the held lock without restoring or releasing another owner's descriptor
    assert outcome is RestoreOutcome.LOCK_HELD
    assert len(lock.acquired) == 1
    assert lock.released == []
    assert restore.calls == []


def test_restore_transaction_reports_restore_error(tmp_path: Path) -> None:
    # GIVEN an atomic restore that fails after the lock is acquired
    settings = AppSettings()
    lock = FakeLock()
    restore = RecordingRestore(RestoreError())
    io = RestoreIO(lock=lock, restore=restore)

    # WHEN running the restore transaction
    outcome = restore_transaction(
        tmp_path / "backups" / "enshrouded-20260529-120000.tar.zst",
        Path(settings.backup_dir),
        SaveDirectories(tmp_path / "saves"),
        restore_io=io,
    )

    # THEN it reports the error and releases the acquired lock
    assert outcome is RestoreOutcome.ERROR
    assert lock.released == [3]
    assert len(restore.calls) == 1
