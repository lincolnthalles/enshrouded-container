"""Auto Rollback — scheduled save restore for Shroud Depot style deployments."""

import logging
import threading
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from enshctl.backup.catalog import select
from enshctl.backup.locking import BackupLock, SystemBackupLock, backup_lock_path
from enshctl.files import chown_tree
from enshctl.restore_flow import RestoreIO, RestoreOutcome, restore_transaction
from enshctl.scheduling import parse_cron

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.config import SaveDirectories
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

ROLLBACK_FALLBACK_INTERVAL = 3600.0


def is_rollback_active(settings: AppSettings) -> bool:
    """Whether auto rollback is enabled."""
    return settings.rollback_enabled


def is_rollback_scheduled(settings: AppSettings) -> bool:
    """Whether a scheduled rollback loop should run."""
    return settings.rollback_enabled and bool(settings.rollback_cron.strip())


def rollback_interval(settings: AppSettings) -> float:
    """Seconds until the next wall-clock rollback tick."""
    return parse_cron(settings.rollback_cron, fallback=ROLLBACK_FALLBACK_INTERVAL) or ROLLBACK_FALLBACK_INTERVAL


def format_next_run(seconds: float) -> str:
    """Human countdown for the next scheduled rollback."""
    total = max(int(seconds), 60)
    hours, remainder = divmod(total, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0 and minutes > 0:
        return f"in {hours}h {minutes}m"
    if hours > 0:
        return f"in {hours}h"
    return f"in {minutes}m" if minutes > 0 else "in 1m"


def describe_startup(settings: AppSettings) -> str:
    """One-line startup summary naming the file, mode, and next run."""
    if settings.rollback_cron.strip():
        return (
            f"Auto rollback: enabled (file={settings.rollback_file}, "
            f"every {settings.rollback_cron.strip()}, "
            f"next run {format_next_run(rollback_interval(settings))})"
        )
    return f"Auto rollback: enabled (file={settings.rollback_file}, on next restart)"


class ChownTree(Protocol):
    """Save-tree ownership seam."""

    def __call__(self, *paths: Path, uid: int, gid: int) -> None: ...


def _apply_save_ownership(
    saves_dir: Path,
    settings: AppSettings,
    *,
    chown: ChownTree | None = None,
) -> None:
    try:
        (chown or chown_tree)(saves_dir, uid=settings.puid, gid=settings.pgid)
    except OSError as exc:
        logger.warning("Auto rollback: could not set ownership on %s: %s", saves_dir, exc)


def resolve_rollback_backup(settings: AppSettings) -> Path | None:
    """Select the configured rollback Backup across every Category by presence."""
    if not settings.rollback_file.strip():
        return None
    return select(Path(settings.backup_dir), file=settings.rollback_file.strip())


def restore_at_startup(
    settings: AppSettings,
    save_directories: SaveDirectories,
    *,
    restore_io: RestoreIO | None = None,
    chown: ChownTree | None = None,
) -> RestoreOutcome | None:
    """Restore the rollback Backup before the first launch; None when disabled."""
    if not is_rollback_active(settings):
        return None
    if not settings.rollback_file.strip():
        logger.error("Auto rollback: ROLLBACK_ENABLED is true but ROLLBACK_FILE is empty")
        return RestoreOutcome.ERROR
    backup_path = resolve_rollback_backup(settings)
    if backup_path is None:
        logger.error("Auto rollback: no matching backup found for %s", settings.rollback_file)
        return RestoreOutcome.ERROR
    logger.info("Auto rollback: restoring %s…", backup_path.name)
    outcome = restore_transaction(
        backup_path,
        Path(settings.backup_dir),
        save_directories,
        restore_io=restore_io or RestoreIO(),
    )
    if outcome is RestoreOutcome.LOCK_HELD:
        logger.error(
            "Auto rollback: cannot acquire backup lock for %s; another backup operation is in progress",
            backup_path.name,
        )
        return outcome
    if outcome is not RestoreOutcome.SUCCESS:
        logger.error("Auto rollback: restore of %s failed", backup_path.name)
        return outcome
    _apply_save_ownership(save_directories.saves_dir, settings, chown=chown)
    logger.info("Auto rollback: restore complete")
    return outcome


def restore_for_restart(
    settings: AppSettings,
    save_directories: SaveDirectories,
    *,
    restore_io: RestoreIO | None = None,
    chown: ChownTree | None = None,
) -> RestoreOutcome | None:
    """Restore the rollback Backup between stop and relaunch; None when disabled."""
    if not is_rollback_active(settings):
        return None
    backup_path = resolve_rollback_backup(settings)
    if backup_path is None:
        logger.error("Auto rollback: no matching backup found for %s", settings.rollback_file or "<empty>")
        return RestoreOutcome.ERROR
    logger.info("Auto rollback: restoring %s…", backup_path.name)
    outcome = restore_transaction(
        backup_path,
        Path(settings.backup_dir),
        save_directories,
        restore_io=restore_io or RestoreIO(),
        wait_seconds=settings.shutdown_backup_wait,
    )
    if outcome is RestoreOutcome.LOCK_HELD:
        logger.error(
            "Auto rollback: backup lock held after %ds for %s; relaunching without restoring",
            settings.shutdown_backup_wait,
            backup_path.name,
        )
        return outcome
    if outcome is not RestoreOutcome.SUCCESS:
        logger.error("Auto rollback: restore of %s failed", backup_path.name)
        return outcome
    _apply_save_ownership(save_directories.saves_dir, settings, chown=chown)
    logger.info("Auto rollback: restore complete, server relaunching")
    return outcome


class RollbackController:
    """Own rollback timing and request one scheduled restart per lifecycle."""

    def __init__(
        self,
        settings: AppSettings,
        rollback_request: threading.Event,
        *,
        clock: Callable[[], float] = monotonic,
        wait: Callable[[threading.Event, float], bool] | None = None,
        lock: BackupLock | None = None,
    ) -> None:
        self._settings = settings
        self._rollback_request = rollback_request
        self._clock = clock
        self._wait = wait or (lambda event, timeout: event.wait(timeout))
        self._lock = lock or SystemBackupLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, stop_event: threading.Event) -> threading.Thread:
        """Start the daemon rollback loop."""
        self._stop_event = stop_event
        thread = threading.Thread(target=self._run, daemon=True, name="auto-rollback")
        self._thread = thread
        thread.start()
        return thread

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception:
            logger.exception("Auto rollback: controller failed; continuing without rollback")

    def _run_loop(self) -> None:
        next_at = self._clock() + rollback_interval(self._settings)
        while not self._stop_event.is_set():
            now = self._clock()
            if now >= next_at:
                if not self._preconditions_pass():
                    if self._stop_event.is_set():
                        return
                    next_at = self._clock() + rollback_interval(self._settings)
                    continue
                self._request_restart()
                return
            self._wait(self._stop_event, max(next_at - now, 1.0))

    def _preconditions_pass(self) -> bool:
        if self._stop_event.is_set():
            return False
        backup_path = resolve_rollback_backup(self._settings)
        if backup_path is None:
            logger.error(
                "Auto rollback: no matching backup found for %s; skipping this tick",
                self._settings.rollback_file or "<empty>",
            )
            return False
        lock_path = backup_lock_path(Path(self._settings.backup_dir))
        deadline = self._clock() + self._settings.shutdown_backup_wait
        while True:
            if self._stop_event.is_set():
                return False
            fd = self._lock.acquire(lock_path, 0)
            if fd is not None:
                self._lock.release(fd)
                return True
            if self._clock() >= deadline:
                logger.warning(
                    "Auto rollback: backup lock held after %ds; skipping this tick",
                    self._settings.shutdown_backup_wait,
                )
                return False
            if self._wait(self._stop_event, 1.0):
                return False

    def _request_restart(self) -> None:
        if self._stop_event.is_set():
            return
        logger.info("Auto rollback: schedule reached, stopping server to restore %s", self._settings.rollback_file)
        self._rollback_request.set()
