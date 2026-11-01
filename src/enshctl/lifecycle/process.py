"""Server process, Wine, environment, and log-tail operations."""

import logging
import subprocess
import threading
import time
from contextlib import suppress
from os import environ
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl import mods
from enshctl.paths import (
    GAME_EXE,
    MANIFESTS_DIR,
    WINE_PREFIX,
    WINE_PREFIX_INIT_MARKER,
    WINE_SERVER_BIN,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from enshctl.lifecycle.types import ServerProcess
    from enshctl.settings import AppSettings

SERVER = 25
logging.addLevelName(SERVER, "GAMESERVER")
logger = logging.getLogger(__name__)

LOG_SEARCH_TIMEOUT = 120


def base_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Minimal allowlist inherited by child processes — never whole `environ`."""
    env = environ if source is None else source
    keep = ("PATH", "LANG", "LC_ALL", "TZ", "HOME", "USER", "LOGNAME", "TMPDIR")
    return {key: value for key in keep if (value := env.get(key)) is not None}


def _wine_env(settings: AppSettings, dll_overrides: str) -> dict[str, str]:
    return {
        **base_env(),
        "WINEPREFIX": f"{WINE_PREFIX}",
        "WINEARCH": settings.winearch,
        "WINEDEBUG": settings.winedebug,
        "HOME": settings.home,
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "WINEDLLOVERRIDES": dll_overrides,
        "XDG_RUNTIME_DIR": f"/var/run/user/{settings.puid}",
    }


def make_server_env(settings: AppSettings, dll_overrides: str) -> dict[str, str]:
    return _wine_env(settings, dll_overrides)


def make_tool_env(settings: AppSettings) -> dict[str, str]:
    return _wine_env(settings, mods.DEFAULT_DLL_OVERRIDES)


def resolve_dll_overrides(settings: AppSettings) -> str:
    if settings.winedlloverrides is not None:
        logger.info("Using user-provided WINEDLLOVERRIDES: %s", settings.winedlloverrides)
        return settings.winedlloverrides
    generated = mods.generate_dll_overrides()
    logger.info("Generated WINEDLLOVERRIDES: %s", generated)
    return generated


def start_server(settings: AppSettings) -> ServerProcess:
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
    env = {**base_env(), **make_server_env(settings, resolve_dll_overrides(settings))}
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd="/data/gameserver", env=env)


def stream_output(process: ServerProcess) -> threading.Thread:
    """Drain server stdout to the logger in a daemon thread."""

    def reader() -> None:
        try:
            if process.stdout is None:
                logger.warning("No server stdout to stream")
                return
            for line in iter(process.stdout.readline, b""):
                decoded = line.decode(errors="replace").rstrip()
                if decoded:
                    logger.log(SERVER, decoded, extra={"source": "gameserver"})
            process.stdout.close()
        except OSError:
            logger.exception("Failed to read server output")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return thread


def signal_game(sig: int) -> bool:
    """Send a signal to the game server process tree, bypassing the runuser wrapper.

    Returns True if at least one signal was delivered.
    """
    delivered = False
    try:
        result = subprocess.run(
            [
                "/usr/bin/runuser",
                "-u",
                "steam",
                "--",
                "pkill",
                f"-{sig}",
                "-f",
                "enshrouded_server.exe",
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except OSError, subprocess.SubprocessError:
        logger.warning("Failed to signal game server process")
        return False
    else:
        delivered = result.returncode == 0
        if not delivered:
            logger.warning("No game server process matched for signal %d", sig)
        return delivered


def find_game_log() -> Path | None:
    """Find the most recently modified game log file."""
    search_roots = (
        Path("/data/logs"),
        Path("/data/gameserver/logs"),
        MANIFESTS_DIR,
        WINE_PREFIX / "drive_c/users/steamuser/AppData/Local/Enshrouded/Saved/Logs",
    )
    candidates: list[Path] = []
    for root in search_roots:
        if root.exists():
            candidates.extend(root.glob("*.log"))
            candidates.extend(root.rglob("logs/*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def tail_log_file(log_path: Path, stop_event: threading.Event) -> None:
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


def start_log_tail_thread(stop_event: threading.Event) -> threading.Thread:
    """Start a background thread that tails the game's log file."""

    def tailer() -> None:
        log_path: Path | None = None
        for _ in range(LOG_SEARCH_TIMEOUT):
            log_path = find_game_log()
            if log_path is not None:
                break
            if stop_event.is_set():
                return
            time.sleep(1)
        if log_path is None:
            logger.warning("[log-tail] No game log file found after %ds, aborted", LOG_SEARCH_TIMEOUT)
            return
        try:
            tail_log_file(log_path, stop_event)
        except OSError:
            logger.exception("Failed to tail game log")

    thread = threading.Thread(target=tailer, daemon=True)
    thread.start()
    return thread


def cleanup_wineserver(settings: AppSettings) -> None:
    env = make_tool_env(settings)
    if WINE_SERVER_BIN.exists():
        logger.info("Cleaning up Wine server")
        try:
            subprocess.run(
                ["/usr/bin/runuser", "-u", "steam", "--", f"{WINE_SERVER_BIN}", "-k"],
                env=env,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Wine server cleanup timed out, forcing with -k9")
            try:
                subprocess.run(
                    ["/usr/bin/runuser", "-u", "steam", "--", f"{WINE_SERVER_BIN}", "-k9"],
                    env=env,
                    timeout=10,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                logger.warning("Forced Wine server cleanup also timed out")
            except OSError:
                logger.warning("Failed to execute forced Wine server cleanup")
        except OSError:
            logger.warning("Failed to execute Wine server cleanup")


def ensure_wineprefix(settings: AppSettings) -> None:
    """Initialize the Wine prefix if it hasn't been set up yet.

    Checks for system.reg — the registry file Wine creates on first init.
    Runs as the steam user so all prefix files have correct ownership.
    """
    if WINE_PREFIX_INIT_MARKER.exists():
        logger.info("Wine prefix already initialized")
        return

    cleanup_wineserver(settings)

    logger.info("Initializing wine prefix at %s", WINE_PREFIX)
    try:
        subprocess.run(
            [
                "/usr/bin/runuser",
                "-u",
                "steam",
                "--",
                "xvfb-run",
                "--auto-servernum",
                "wine",
                "wineboot",
                "--init",
            ],
            env=make_tool_env(settings),
            timeout=60,
            check=True,
        )
    except subprocess.CalledProcessError:
        logger.exception("Wine prefix initialization failed")
        raise
    except subprocess.TimeoutExpired:
        logger.exception("Wine prefix initialization timed out after 60s")
        raise
    else:
        WINE_PREFIX_INIT_MARKER.touch()
