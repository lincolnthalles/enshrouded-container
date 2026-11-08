"""Tests for the shared backup lock policy."""

from typing import TYPE_CHECKING

from enshctl.backup.locking import SystemBackupLock

if TYPE_CHECKING:
    from pathlib import Path


def test_system_backup_lock_acquires_without_waiting(tmp_path: Path) -> None:
    # GIVEN a lock available immediately
    sleeps: list[float] = []
    lock = SystemBackupLock(
        acquire_file=lambda _path: 3,
        release_file=lambda _fd: None,
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )

    # WHEN acquiring without a wait budget
    fd = lock.acquire(tmp_path / ".lock")

    # THEN it returns the descriptor without sleeping
    assert fd == 3
    assert sleeps == []


def test_system_backup_lock_waits_until_acquired(tmp_path: Path) -> None:
    # GIVEN a lock that becomes available after one wait interval
    results = iter([None, 3])
    clocks = iter([0.0, 0.5])
    sleeps: list[float] = []
    lock = SystemBackupLock(
        acquire_file=lambda _path: next(results),
        release_file=lambda _fd: None,
        clock=lambda: next(clocks),
        sleep=sleeps.append,
    )

    # WHEN acquiring with a one-second budget
    fd = lock.acquire(tmp_path / ".lock", wait_seconds=1)

    # THEN it sleeps once and returns the acquired descriptor
    assert fd == 3
    assert sleeps == [1]


def test_system_backup_lock_returns_none_after_wait_budget(tmp_path: Path) -> None:
    # GIVEN a lock that stays held past the budget
    results = iter([None, None])
    clocks = iter([0.0, 0.5, 1.5])
    sleeps: list[float] = []
    lock = SystemBackupLock(
        acquire_file=lambda _path: next(results),
        release_file=lambda _fd: None,
        clock=lambda: next(clocks),
        sleep=sleeps.append,
    )

    # WHEN acquiring with a one-second budget
    fd = lock.acquire(tmp_path / ".lock", wait_seconds=1)

    # THEN it sleeps once and reports the lock as held
    assert fd is None
    assert sleeps == [1]


def test_system_backup_lock_defaults_to_non_blocking(tmp_path: Path) -> None:
    # GIVEN the production lock adapter
    lock = SystemBackupLock()

    # WHEN one descriptor holds the lock and another tries to acquire it
    held = lock.acquire(tmp_path / ".lock")
    contended = lock.acquire(tmp_path / ".lock")

    # THEN the second attempt reports the lock as held
    assert held is not None
    assert contended is None

    # AND releasing the held descriptor makes the lock available again
    lock.release(held)
    reacquired = lock.acquire(tmp_path / ".lock")
    assert reacquired is not None
    lock.release(reacquired)


def test_system_backup_lock_release_delegates() -> None:
    # GIVEN a lock whose release is recorded
    released: list[int] = []
    lock = SystemBackupLock(release_file=released.append)

    # WHEN releasing a descriptor
    lock.release(3)

    # THEN the descriptor reaches the release adapter
    assert released == [3]
