"""Parent-side backup spawning and the scheduled live-backup loop."""

import logging
import re
import subprocess
import threading
from os import environ
from typing import TYPE_CHECKING

from enshctl.backup_protocol import BackupOutcome, BackupRequest, Trigger
from enshctl.lifecycle.env import base_env
from enshctl.scheduling import parse_cron
from enshctl.settings import backup_child_env

if TYPE_CHECKING:
    from collections.abc import Mapping

BACKUP = 26
logging.addLevelName(BACKUP, "BACKUP")
logger = logging.getLogger(__name__)

_CHILD_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[\w+\] ")


def run_backup(request: BackupRequest | None = None, *, env: Mapping[str, str] | None = None) -> None:
    """Run a backup subprocess for the given request (live by default)."""
    request = request or BackupRequest.for_trigger(Trigger.SCHEDULED)
    source = environ if env is None else env
    child_env = {**base_env(source), **backup_child_env(source)}
    try:
        cmd = ["enshctl", "backup", *request.to_argv()]
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            env=child_env,
            start_new_session=request.detach,
        )
    except OSError as exc:
        logger.warning("Failed to spawn backup subprocess: %s", exc)
        return
    output = (result.stdout + result.stderr).decode(errors="replace").strip()
    try:
        outcome = BackupOutcome(result.returncode)
    except ValueError:
        logger.warning("Backup subprocess returned unknown exit code %d: %s", result.returncode, output)
        return
    if outcome == BackupOutcome.SUCCESS:
        for line in output.splitlines():
            logger.log(BACKUP, _strip_child_prefix(line))
    elif outcome == BackupOutcome.LOCK_HELD:
        if request.wait_seconds > 0:
            logger.warning("%s backup skipped: lock held by another process", request.category.capitalize())
        else:
            logger.debug("Backup skipped: lock held by another process")
    else:
        for line in output.splitlines():
            logger.log(BACKUP, _strip_child_prefix(line))


def start_scheduler(cron_expr: str, stop_event: threading.Event) -> threading.Thread:
    """Start the daemon thread that runs scheduled live backups."""
    thread = threading.Thread(target=_scheduler_loop, args=(cron_expr, stop_event), daemon=True)
    thread.start()
    return thread


def _scheduler_loop(cron_expr: str, stop_event: threading.Event) -> None:
    """Run scheduled backups as subprocesses. First backup runs immediately."""
    if stop_event.is_set():
        return
    run_backup(BackupRequest.for_trigger(Trigger.SCHEDULED))
    while not stop_event.is_set():
        interval = parse_cron(cron_expr)
        if interval is None:
            interval = 1200.0
        if stop_event.wait(interval):
            break
        if stop_event.is_set():
            break
        run_backup(BackupRequest.for_trigger(Trigger.SCHEDULED))


def _strip_child_prefix(line: str) -> str:
    return _CHILD_PREFIX_RE.sub("", line)
