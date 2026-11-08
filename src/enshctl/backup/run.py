"""Backup child execution — one request through lock, plan, creation, and retention."""

import logging
import subprocess
from dataclasses import dataclass, field
from os import getpid, nice
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from enshctl.backup.core import BackupPlan, create_backup as create_backup_impl, resolve_format
from enshctl.backup.locking import LOCK_FILE, BackupLock, SystemBackupLock
from enshctl.backup_protocol import BackupOutcome, BackupRequest
from enshctl.config import generated_save_directories, resolve_save_directory
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


class BackupCreator(Protocol):
    """Backup creation seam."""

    def __call__(self, category: Category, plan: BackupPlan, *, space: SpaceGuard) -> Path | None: ...


def _saves_dir(settings: AppSettings) -> Path:
    return generated_save_directories(settings=settings).saves_dir


@dataclass(frozen=True)
class BackupSeams:
    """System and test seams for one backup child run."""

    lock: BackupLock = field(default_factory=SystemBackupLock)
    space_guard: SpaceGuard = field(default_factory=SpaceGuard)
    resolve_saves_dir: Callable[[AppSettings], Path] = _saves_dir
    create_backup: BackupCreator = create_backup_impl
    lower_priority: Callable[[], None] = lower_priority


def run_request(request: BackupRequest, settings: AppSettings, *, seams: BackupSeams) -> BackupOutcome:
    """Run one backup request through priority, lock, plan, creation, and retention."""
    seams.lower_priority()
    category = request.category
    fmt = resolve_format(request.fmt) if request.fmt is not None else None

    lock_path = Path(settings.backup_dir) / LOCK_FILE
    lock_fd = seams.lock.acquire(lock_path, request.wait_seconds)
    if lock_fd is None:
        if request.wait_seconds > 0:
            logger.warning("Backup lock still held after %ds wait, skipping backup", request.wait_seconds)
        else:
            logger.info("Lock held by another process, skipping backup")
        return BackupOutcome.LOCK_HELD

    try:
        if request.saves_dir is not None:
            saves_dir = resolve_save_directory(
                str(request.saves_dir),
                backup_dir=Path(settings.backup_dir),
                origin="Backup request Save directory",
            )
        else:
            saves_dir = seams.resolve_saves_dir(settings)
        plan = BackupPlan.from_settings(
            settings,
            saves_dir=saves_dir,
            fmt=fmt,
            level=request.level,
        )
        result = seams.create_backup(category, plan, space=seams.space_guard)
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
