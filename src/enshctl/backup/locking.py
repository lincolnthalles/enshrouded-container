"""File locking for backup operations."""

import fcntl
import os
from contextlib import suppress
from pathlib import Path

LOCK_FILE = ".lock"


def acquire_lock(lock_path: str | Path, blocking: bool = True) -> int | None:
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        fcntl.flock(fd, flags)
    except BlockingIOError:
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
