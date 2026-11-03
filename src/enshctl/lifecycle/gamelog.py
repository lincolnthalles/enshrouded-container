"""Game log discovery and tailing."""

import logging
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.paths import MANIFESTS_DIR, WINE_PREFIX

if TYPE_CHECKING:
    from collections.abc import Iterable

SERVER = 25
logging.addLevelName(SERVER, "GAMESERVER")
logger = logging.getLogger(__name__)

LOG_SEARCH_TIMEOUT = 120

_SEARCH_ROOTS = (
    Path("/data/logs"),
    Path("/data/gameserver/logs"),
    MANIFESTS_DIR,
    WINE_PREFIX / "drive_c/users/steamuser/AppData/Local/Enshrouded/Saved/Logs",
)


def find_latest(*, search_roots: Iterable[Path] | None = None) -> Path | None:
    """Find the most recently modified game log file."""
    roots = _SEARCH_ROOTS if search_roots is None else search_roots
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(root.glob("*.log"))
            candidates.extend(root.rglob("logs/*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def tail(log_path: Path, stop_event: threading.Event) -> None:
    """Tail a log file through the logger, stopping when stop_event is set."""
    logger.info("Tailing log file: %s", log_path)
    proc = subprocess.Popen(
        ["tail", "-f", "-n", "+1", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def _terminate_on_stop() -> None:
        stop_event.wait()
        with suppress(OSError):
            proc.terminate()

    watcher = threading.Thread(target=_terminate_on_stop, daemon=True)
    watcher.start()
    lines_relayed = 0
    try:
        if proc.stdout is not None:
            for line in iter(proc.stdout.readline, b""):
                if stop_event.is_set():
                    break
                decoded = line.decode(errors="replace").rstrip()
                if decoded:
                    logger.info(decoded, extra={"source": "gameserver"})
                    lines_relayed += 1
    finally:
        with suppress(OSError):
            proc.terminate()
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)
    logger.info("Log tail ended, %d lines relayed", lines_relayed)


def start_tail(
    stop_event: threading.Event,
    *,
    search_roots: Iterable[Path] | None = None,
) -> threading.Thread:
    """Start a background thread that tails the game's log file."""

    def tailer() -> None:
        log_path: Path | None = None
        for _ in range(LOG_SEARCH_TIMEOUT):
            log_path = find_latest(search_roots=search_roots)
            if log_path is not None:
                break
            if stop_event.is_set():
                return
            time.sleep(1)
        if log_path is None:
            logger.warning("[log-tail] No game log file found after %ds, aborted", LOG_SEARCH_TIMEOUT)
            return
        try:
            tail(log_path, stop_event)
        except OSError:
            logger.exception("Failed to tail game log")

    thread = threading.Thread(target=tailer, daemon=True)
    thread.start()
    return thread
