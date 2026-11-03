"""Backup child execution — one request through lock, plan, creation, and retention."""

import logging
import subprocess
import time
from dataclasses import dataclass, field
from os import getpid, nice
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from enshctl.backup.core import BackupPlan, create_backup, resolve_format
from enshctl.backup.locking import LOCK_FILE, acquire_lock, release_lock
from enshctl.backup_protocol import BackupOutcome, BackupRequest
from enshctl.config import generated_save_directories
from enshctl.disk_space import SpaceGuard
from enshctl.retention import RetentionPolicy

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.backup.category import Category
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

_priority_state = {"warned": False}


def lower_priority() -> None:
    """Lower CPU and IO priority, warning once per run if unavailable."""
    try:
        nice(19)
    except OSError:
        _warn_priority_once("SYS_NICE cap unavailable, backup runs at default CPU priority")

    try:
        subprocess.run(
            ["ionice", "-c3", "-p", str(getpid())],
            capture_output=True,
            check=True,
        )
    except OSError, subprocess.CalledProcessError:
        _warn_priority_once("ionice unavailable, backup runs at default IO priority")


def _warn_priority_once(message: str) -> None:
    if _priority_state["warned"]:
        logger.debug(message)
        return
    logger.warning(message)
    _priority_state["warned"] = True


class BackupLock(Protocol):
    """Non-blocking backup lock seam."""

    def acquire(self, path: Path) -> int | None: ...

    def release(self, fd: int) -> None: ...


class SystemBackupLock:
    """Production lock adapter over the file-locking module."""

    def acquire(self, path: Path) -> int | None:
        return acquire_lock(path, blocking=False)

    def release(self, fd: int) -> None:
        release_lock(fd)


class BackupClock(Protocol):
    """Monotonic clock and sleep seam for lock waiting."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemBackupClock:
    """Production clock adapter."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class BackupCreator(Protocol):
    """Backup creation seam."""

    def __call__(self, category: Category, plan: BackupPlan, *, space: SpaceGuard) -> Path | None: ...


def _saves_dir(settings: AppSettings) -> Path:
    return generated_save_directories(settings=settings).saves_dir


@dataclass(frozen=True)
class BackupSeams:
    """System and test seams for one backup child run."""

    lock: BackupLock = field(default_factory=SystemBackupLock)
    clock: BackupClock = field(default_factory=SystemBackupClock)
    space: SpaceGuard = field(default_factory=SpaceGuard)
    saves_dir: Callable[[AppSettings], Path] = _saves_dir
    create: BackupCreator = create_backup
    lower_priority: Callable[[], None] = lower_priority


def run_request(request: BackupRequest, settings: AppSettings, *, seams: BackupSeams) -> BackupOutcome:
    """Run one backup request through priority, lock, plan, creation, and retention."""
    seams.lower_priority()
    category = request.category
    fmt = resolve_format(request.fmt) if request.fmt is not None else None

    lock_path = Path(settings.backup_dir) / LOCK_FILE
    lock_fd = seams.lock.acquire(lock_path)
    waited = False
    if lock_fd is None and request.wait_seconds > 0:
        waited = True
        deadline = seams.clock.monotonic() + request.wait_seconds
        while lock_fd is None and seams.clock.monotonic() < deadline:
            seams.clock.sleep(1)
            lock_fd = seams.lock.acquire(lock_path)
    if lock_fd is None:
        if waited:
            logger.warning("Backup lock still held after %ds wait, skipping backup", request.wait_seconds)
        else:
            logger.info("Lock held by another process, skipping backup")
        return BackupOutcome.LOCK_HELD

    try:
        plan = BackupPlan.from_settings(settings, saves_dir=seams.saves_dir(settings), fmt=fmt, level=request.level)
        result = seams.create(category, plan, space=seams.space)
        if result is not None:
            deleted = RetentionPolicy.from_settings(settings).enforce(categories=(category,))[category]
            if deleted:
                logger.info("Pruned %d backup(s) from %s", len(deleted), category)
    except OSError, ValueError:
        logger.exception("Backup failed")
        return BackupOutcome.ERROR
    finally:
        seams.lock.release(lock_fd)

    return BackupOutcome.SUCCESS
