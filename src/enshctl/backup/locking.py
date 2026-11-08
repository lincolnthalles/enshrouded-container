"""File locking for backup operations."""

import fcntl
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

LOCK_FILE = ".lock"


def backup_lock_path(backup_dir: Path) -> Path:
    return backup_dir / LOCK_FILE


def acquire_lock(lock_path: str | Path, blocking: bool = True) -> int | None:
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flags)
    except BlockingIOError:
        with suppress(OSError):
            os.close(fd)
        return None
    else:
        return fd


def release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        with suppress(OSError):
            os.close(fd)


def _acquire_nonblocking(path: Path) -> int | None:
    return acquire_lock(path, blocking=False)


class BackupLock(Protocol):
    """Exclusive lock with an optional wait budget."""

    def acquire(self, path: Path, wait_seconds: int = 0) -> int | None: ...

    def release(self, fd: int) -> None: ...


@dataclass(frozen=True)
class SystemBackupLock:
    """Production lock adapter — non-blocking flock with an optional wait budget."""

    acquire_file: Callable[[Path], int | None] = _acquire_nonblocking
    release_file: Callable[[int], None] = release_lock
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def acquire(self, path: Path, wait_seconds: int = 0) -> int | None:
        fd = self.acquire_file(path)
        if fd is not None or wait_seconds <= 0:
            return fd
        deadline = self.clock() + wait_seconds
        while fd is None and self.clock() < deadline:
            self.sleep(1)
            fd = self.acquire_file(path)
        return fd

    def release(self, fd: int) -> None:
        self.release_file(fd)
