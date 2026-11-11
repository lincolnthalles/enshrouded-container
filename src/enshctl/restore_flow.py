"""Restore orchestration — guarded lock and atomic restore through explicit system seams."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from enshctl.backup.locking import BackupLock, SystemBackupLock, backup_lock_path
from enshctl.config import SaveDirectories, generated_save_directories
from enshctl.disk_space import SpaceGuard
from enshctl.pidfile import PidFile
from enshctl.restore import RestoreError, restore_backup

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from enshctl.settings import AppSettings


class PidGuard(Protocol):
    """Server-running guard seam."""

    def is_active(self) -> bool: ...


class RestoreCallable(Protocol):
    """Atomic restore seam."""

    def __call__(
        self,
        backup_path: Path,
        *,
        saves_dir: Path,
        tmp_dir: Path,
        space: SpaceGuard,
    ) -> None: ...


class RestoreOutcome(StrEnum):
    """One restore transaction outcome."""

    SUCCESS = "success"
    LOCK_HELD = "lock-held"
    ERROR = "error"


def _resolve_save_directories(settings: AppSettings) -> SaveDirectories:
    return generated_save_directories(settings=settings)


@dataclass(frozen=True)
class RestoreIO:
    """System effects for one restore invocation."""

    pid_file: PidGuard = field(default_factory=PidFile)
    resolve_save_directories: Callable[[AppSettings], SaveDirectories] = _resolve_save_directories
    space_guard: SpaceGuard = field(default_factory=SpaceGuard)
    lock: BackupLock = field(default_factory=SystemBackupLock)
    restore: RestoreCallable = restore_backup


def restore_transaction(
    backup_path: Path,
    backup_dir: Path,
    save_directories: SaveDirectories,
    *,
    restore_io: RestoreIO,
    wait_seconds: int = 0,
) -> RestoreOutcome:
    """Hold the backup lock and restore one Backup atomically."""
    lock_fd = restore_io.lock.acquire(backup_lock_path(backup_dir), wait_seconds)
    if lock_fd is None:
        return RestoreOutcome.LOCK_HELD
    try:
        restore_io.restore(
            backup_path,
            saves_dir=save_directories.saves_dir,
            tmp_dir=save_directories.restore_tmp_dir,
            space=restore_io.space_guard,
        )
    except RestoreError:
        return RestoreOutcome.ERROR
    finally:
        restore_io.lock.release(lock_fd)
    return RestoreOutcome.SUCCESS
