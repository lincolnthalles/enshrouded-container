"""Server process control — launch, output streaming, discovery, and signaling."""

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from enshctl.lifecycle import gamelog, wine
from enshctl.paths import GAME_EXE

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from enshctl.lifecycle.types import ServerProcess
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

_PROC_ROOT = Path("/proc")
_MAX_SERVER_LINE_BYTES = 32_768
_SERVER_READ_SIZE = _MAX_SERVER_LINE_BYTES + 2
_TREE_SCAN_INTERVAL = 0.25
_TREE_SCAN_TIMEOUT = 2.0
_TREE_SCAN_ATTEMPTS = 8
_STATE_TIMEOUT = 2.0
_STATE_POLL = 0.05
_STATE_POLL_ATTEMPTS = 40


@dataclass(frozen=True)
class WineTree:
    """Game PID plus the Wine services that belong to the same paused tree."""

    game_pid: int
    service_pids: tuple[int, ...]


def start(
    settings: AppSettings,
    *,
    source: Mapping[str, str] | None = None,
) -> ServerProcess:
    cmd = [
        "/usr/bin/runuser",
        "-u",
        "steam",
        "--",
        "xvfb-run",
        "--auto-servernum",
        '--server-args="-screen 0 90x90x1"',  # Lower the allocated memory for the X server.
        "wine",
        str(GAME_EXE),
    ]
    logger.info("Starting server: %s", cmd)
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd="/data/gameserver",
        env=wine.server_env(settings, source=source),
    )


def _read_bounded_line(stream: IO[bytes]) -> tuple[bytes, bool] | None:
    """Read one line, discarding the remainder when it exceeds the byte cap."""
    chunk = stream.readline(_SERVER_READ_SIZE)
    if not chunk:
        return None
    if chunk.endswith(b"\n"):
        payload = chunk[:-1]
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        return (b"", True) if len(payload) > _MAX_SERVER_LINE_BYTES else (payload, False)
    if len(chunk) > _MAX_SERVER_LINE_BYTES:
        while True:
            remainder = stream.readline(_SERVER_READ_SIZE)
            if not remainder or remainder.endswith(b"\n"):
                break
        return b"", True
    return chunk, False


def stream(
    process: ServerProcess,
    *,
    on_line: Callable[[str], None] | None = None,
) -> threading.Thread:
    """Drain server stdout to the logger in a daemon thread."""

    def reader() -> None:
        hook_failed = False
        try:
            stdout = process.stdout
            if stdout is None:
                logger.warning("No server stdout to stream")
                return
            while True:
                result = _read_bounded_line(stdout)
                if result is None:
                    break
                line, overlong = result
                if overlong:
                    logger.warning("Discarding overlong server output line (>%d bytes)", _MAX_SERVER_LINE_BYTES)
                    continue
                decoded = line.decode(errors="replace").rstrip()
                if not decoded:
                    continue
                logger.log(gamelog.SERVER, decoded, extra={"source": "gameserver"})
                if on_line is None:
                    continue
                try:
                    on_line(decoded)
                except Exception:
                    if not hook_failed:
                        logger.warning("Presence callback failed; continuing to relay output", exc_info=True)
                        hook_failed = True
            stdout.close()
        except OSError:
            logger.exception("Failed to read server output")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return thread


def signal_game(sig: int, *, proc_root: Path = _PROC_ROOT) -> bool:
    """Send a signal to the resolved game PID after verifying its argv[0]."""
    game_pid, _services = _discover_matching(proc_root)
    if game_pid is None:
        logger.warning("No game server process matched for signal %d", sig)
        return False
    cmdline = _read_cmdline(game_pid, proc_root)
    if not cmdline or cmdline[0] != str(GAME_EXE):
        logger.warning("Refusing to signal PID %d: argv[0] does not match the game", game_pid)
        return False
    try:
        os.kill(game_pid, sig)
    except OSError:
        logger.warning("Failed to signal game server PID %d", game_pid)
        return False
    return True


def signal_pid(pid: int, sig: int) -> bool:
    """Send a signal to a PID previously discovered in the Wine tree."""
    try:
        os.kill(pid, sig)
    except OSError:
        logger.warning("Failed to signal Wine PID %d", pid)
        return False
    return True


def wine_tree(
    *,
    proc_root: Path = _PROC_ROOT,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WineTree | None:
    """Return a stable Wine tree, or None when the game is missing or unstable."""
    previous: WineTree | None = None
    deadline = clock() + _TREE_SCAN_TIMEOUT
    for _ in range(_TREE_SCAN_ATTEMPTS):
        current = _discover_wine_tree(proc_root)
        if current is not None and current == previous:
            return current
        previous = current
        if clock() >= deadline:
            return None
        sleep(_TREE_SCAN_INTERVAL)
    return None


def suspend_all(
    *,
    proc_root: Path = _PROC_ROOT,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Stop the game and its Wine services, rolling back on any verification failure."""
    tree = wine_tree(proc_root=proc_root, sleep=sleep, clock=clock)
    if tree is None:
        logger.warning("Refusing to pause: Wine tree is missing or unstable")
        return False
    pids = (tree.game_pid, *tree.service_pids)
    for pid in pids:
        if not signal_pid(pid, signal.SIGSTOP):
            resume_all(proc_root=proc_root, sleep=sleep, clock=clock)
            return False
    if not _wait_for_state(pids, "T", proc_root=proc_root, sleep=sleep, clock=clock):
        logger.error("Auto Pause suspend verification failed; resuming the Wine tree")
        resume_all(proc_root=proc_root, sleep=sleep, clock=clock)
        return False
    matching = set(_scan_matching_pids(proc_root))
    stopped_drift = {pid for pid in matching - set(pids) if _read_state(pid, proc_root) == "T"}
    if stopped_drift:
        logger.error("Auto Pause found a stopped Wine process outside the tree: %s", sorted(stopped_drift))
        resume_all(proc_root=proc_root, sleep=sleep, clock=clock)
        return False
    return True


def resume_all(
    *,
    proc_root: Path = _PROC_ROOT,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Resume every matching Wine/game process, retrying verification once."""
    game_pid, services = _discover_matching(proc_root)
    pids = (*services, game_pid) if game_pid is not None else services
    if not pids:
        return True
    for pid in pids:
        signal_pid(pid, signal.SIGCONT)
    for attempt in range(2):
        if _wait_for_no_state(pids, "T", proc_root=proc_root, sleep=sleep, clock=clock):
            return True
        if attempt == 0:
            logger.warning("Auto Pause resume verification failed; retrying SIGCONT")
            for pid in pids:
                signal_pid(pid, signal.SIGCONT)
    logger.error("Auto Pause resume verification failed after retry")
    return False


def _discover_wine_tree(proc_root: Path) -> WineTree | None:
    game_pid, services = _discover_matching(proc_root)
    if game_pid is None:
        return None
    return WineTree(game_pid, services)


def _discover_matching(proc_root: Path) -> tuple[int | None, tuple[int, ...]]:
    game_pid: int | None = None
    services: list[int] = []
    for pid in _process_ids(proc_root):
        if _read_state(pid, proc_root) == "Z":
            continue
        cmdline = _read_cmdline(pid, proc_root)
        if cmdline and cmdline[0] == str(GAME_EXE):
            game_pid = pid
            continue
        if _is_wine_service(pid, cmdline, proc_root):
            services.append(pid)
    return game_pid, tuple(sorted(services))


def _scan_matching_pids(proc_root: Path) -> tuple[int, ...]:
    game_pid, services = _discover_matching(proc_root)
    if game_pid is None:
        return services
    return tuple(sorted((game_pid, *services)))


def _process_ids(proc_root: Path) -> list[int]:
    try:
        entries = proc_root.iterdir()
    except OSError:
        return []
    return sorted(int(entry.name) for entry in entries if entry.name.isdigit())


def _read_cmdline(pid: int, proc_root: Path) -> tuple[str, ...] | None:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return tuple(part.decode(errors="replace") for part in raw.rstrip(b"\x00").split(b"\x00"))


def _read_state(pid: int, proc_root: Path) -> str | None:
    try:
        stat = (proc_root / str(pid) / "stat").read_text()
    except OSError:
        return None
    try:
        return stat.rsplit(")", 1)[1].split()[0]
    except IndexError:
        return None


def _read_text(pid: int, name: str, proc_root: Path) -> str | None:
    try:
        return (proc_root / str(pid) / name).read_text().strip()
    except OSError:
        return None


def _is_wine_service(pid: int, cmdline: tuple[str, ...] | None, proc_root: Path) -> bool:
    if _read_text(pid, "comm", proc_root) == "wineserver":
        return True
    try:
        executable = str((proc_root / str(pid) / "exe").readlink())
    except OSError:
        executable = ""
    if "wine" in executable.lower():
        return True
    return bool(cmdline and cmdline[0].lower().startswith("c:\\windows\\"))


def _wait_for_state(
    pids: tuple[int, ...],
    state: str,
    *,
    proc_root: Path,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> bool:
    deadline = clock() + _STATE_TIMEOUT
    for _ in range(_STATE_POLL_ATTEMPTS):
        if all(_read_state(pid, proc_root) == state for pid in pids):
            return True
        if clock() >= deadline:
            return False
        sleep(_STATE_POLL)
    return False


def _wait_for_no_state(
    pids: tuple[int, ...],
    state: str,
    *,
    proc_root: Path,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> bool:
    deadline = clock() + _STATE_TIMEOUT
    for _ in range(_STATE_POLL_ATTEMPTS):
        if all(_read_state(pid, proc_root) != state for pid in pids):
            return True
        if clock() >= deadline:
            return False
        sleep(_STATE_POLL)
    return False
