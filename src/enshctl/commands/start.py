"""Start subcommand — full server lifecycle."""

import logging
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from os import chown, environ
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl import backup, config, install, mods
from enshctl.resources import start_resource_poller
from enshctl.settings import (
    GAME_EXE,
    MANIFESTS_DIR,
    PIDFILE,
    WINE_PREFIX,
    WINE_PREFIX_INIT_MARKER,
    WINE_SERVER_BIN,
    load_settings,
)
from enshctl.utils import get_uid_gid, is_truthy

if TYPE_CHECKING:
    from collections.abc import Callable

SERVER = 25
logging.addLevelName(SERVER, "GAMESERVER")
BACKUP = 26
logging.addLevelName(BACKUP, "BACKUP")
logger = logging.getLogger(__name__)

DEFAULT_CRON = "*/60 * * * *"
LOG_SEARCH_TIMEOUT = 120


WINEENV = {
    "WINEPREFIX": f"{WINE_PREFIX}",
    "WINEARCH": environ.get("WINEARCH", "win64"),
    "WINEDEBUG": environ.get("WINEDEBUG", "fixme-all"),
    "HOME": environ.get("HOME", "/home/steam"),
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "WINEDLLOVERRIDES": "mscoree,mshtml=",
    "XDG_RUNTIME_DIR": f"/var/run/user/${environ.get('PUID', '1000')}",
}


class ServerContext:
    """Mutable container for server process state, avoiding module-level globals."""

    def __init__(self) -> None:
        self.server_process: subprocess.Popen[bytes] | None = None
        self.shutdown_requested = False


def _setup_directories() -> None:
    uid, gid = get_uid_gid()
    xdg_dir = f"/var/run/user/{uid}"
    dirs = [
        "/data/saves",
        "/data/logs",
        "/data/backups",
        "/data/mods",
        MANIFESTS_DIR,
        "/data/config",
        xdg_dir,
        WINE_PREFIX,
    ]

    logger.info("Recursively setting permissions for working directories under /data")
    logger.info("UID: %d, GID: %d", uid, gid)
    paths = (Path(str(p)) for p in dirs)
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            chown(p, uid, gid)
        for child in p.rglob("*"):
            with suppress(OSError):
                chown(child, uid, gid)


def _setup_x11_socket() -> None:
    x11_dir = Path("/tmp/.X11-unix")
    x11_dir.mkdir(parents=True, exist_ok=True)
    x11_dir.chmod(0o1777)


def _resolve_dll_overrides() -> str:
    user_override = environ.get("WINEDLLOVERRIDES")
    if user_override is not None:
        logger.info("Using user-provided WINEDLLOVERRIDES: %s", user_override)
        return user_override
    generated = mods.generate_dll_overrides()
    logger.info("Generated WINEDLLOVERRIDES: %s", generated)
    return generated


def _start_server() -> subprocess.Popen[bytes]:
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
    env = WINEENV.copy()
    env["WINEDLLOVERRIDES"] = _resolve_dll_overrides()
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd="/data/gameserver", env=env)


def _stream_output(proc: subprocess.Popen[bytes]) -> None:
    """Stream server stdout line by line to the container console."""
    if proc.stdout is None:
        msg = "No stdout to stream"
        raise RuntimeError(msg)

    for line in iter(proc.stdout.readline, b""):
        decoded = line.decode(errors="replace").rstrip()
        if decoded:
            logger.log(SERVER, decoded, extra={"source": "gameserver"})
    proc.stdout.close()


def _run_backup(extra_args: list[str] | None = None) -> None:
    """Run a backup subprocess. Pass extra_args like ["--cold"] or ["--emergency"]."""
    try:
        cmd = ["enshctl", "backup"]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, check=False, env={**environ, "ORCHESTRATOR_LOG_FILE": ""})
        output = (result.stdout + result.stderr).decode(errors="replace").strip()
        if result.returncode == 0:
            for line in output.splitlines():
                logger.log(BACKUP, _strip_child_prefix(line))
        elif result.returncode == 1:
            logger.debug("Backup skipped: lock held by another process")
        else:
            for line in output.splitlines():
                logger.log(BACKUP, _strip_child_prefix(line))
    except OSError as exc:
        logger.warning("Failed to spawn backup subprocess: %s", exc)


def _make_sigterm_handler(context: ServerContext) -> Callable[[int, object], None]:
    def handler(_signum: int, _frame: object) -> None:
        logger.info("Received SIGTERM, initiating graceful shutdown...")
        context.shutdown_requested = True

        if context.server_process and context.server_process.poll() is None:
            logger.info("Sending SIGINT to server process")
            _cleanup_wineserver()

            context.server_process.send_signal(signal.SIGINT)
            try:
                context.server_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                context.server_process.kill()
                context.server_process.wait()

        if is_truthy("BACKUP_COLD", default=True) and backup.backup_needed():
            logger.info("Creating cold shutdown backup")
            _run_backup(["--cold"])

        PIDFILE.unlink(missing_ok=True)
        logger.info("Shutdown complete")
        sys.exit(0)

    return handler


def _find_game_log() -> Path | None:
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


def _tail_log_file(log_path: Path, stop_event: threading.Event) -> None:
    """Tail a log file through the logger, stopping when stop_event is set."""
    logger.info("Tailing log file: %s", log_path)
    proc = subprocess.Popen(
        ["tail", "-f", "-n", "+1", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
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
        proc.terminate()
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)
    logger.info("Log tail ended, %d lines relayed", lines_relayed)


def _start_log_tail_thread(stop_event: threading.Event) -> threading.Thread:
    """Start a background thread that tails the game's log file."""

    def tailer() -> None:
        log_path: Path | None = None
        for _ in range(LOG_SEARCH_TIMEOUT):
            log_path = _find_game_log()
            if log_path is not None:
                break
            if stop_event.is_set():
                return
            time.sleep(1)
        if log_path is None:
            logger.warning("[log-tail] No game log file found after %ds, aborted", LOG_SEARCH_TIMEOUT)
            return
        _tail_log_file(log_path, stop_event)

    thread = threading.Thread(target=tailer, daemon=True)
    thread.start()
    return thread


def _cleanup_wineserver() -> None:
    if WINE_SERVER_BIN.exists():
        logger.info("Cleaning up Wine server")
        try:
            subprocess.run(
                ["/usr/bin/runuser", "-u", "steam", "--", f"{WINE_SERVER_BIN}", "-k"],
                env=WINEENV,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Wine server cleanup timed out, forcing with -k9")
            try:
                subprocess.run(
                    ["/usr/bin/runuser", "-u", "steam", "--", f"{WINE_SERVER_BIN}", "-k9"],
                    env=WINEENV,
                    timeout=10,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                logger.warning("Forced Wine server cleanup also timed out")
            except OSError:
                logger.warning("Failed to execute forced Wine server cleanup")
        except OSError:
            logger.warning("Failed to execute Wine server cleanup")


def _ensure_wineprefix() -> None:
    """Initialize the Wine prefix if it hasn't been set up yet.

    Checks for system.reg — the registry file Wine creates on first init.
    Runs as the steam user so all prefix files have correct ownership.
    """
    if WINE_PREFIX_INIT_MARKER.exists():
        logger.info("Wine prefix already initialized")
        return

    _cleanup_wineserver()

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
            env=WINEENV,
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


def _setup_timezone() -> None:
    tz = environ.get("TZ", "UTC")
    zone_path = Path(f"/usr/share/zoneinfo/{tz}")
    if zone_path.exists():
        localtime = Path("/etc/localtime")
        if localtime.is_symlink() or localtime.exists():
            localtime.unlink()
        localtime.symlink_to(zone_path)
        environ["TZ"] = tz
        with suppress(AttributeError):
            time.tzset()  # musl libc on Alpine does not support tzset
        logger.info("Timezone set to %s", tz)
    else:
        logger.warning("Timezone %s not found, defaulting to UTC", tz)
        environ["TZ"] = "UTC"


def _scheduler_loop(cron_expr: str) -> None:
    """Run scheduled backups as subprocesses. First backup runs immediately."""
    _run_backup()
    while True:
        interval = backup.parse_cron(cron_expr)
        if interval is None:
            interval = 1200.0
        time.sleep(interval)
        _run_backup()


_CHILD_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[\w+\] ")


def _strip_child_prefix(line: str) -> str:
    return _CHILD_PREFIX_RE.sub("", line)


def run() -> None:
    """Run the start subcommand — full server lifecycle."""
    settings = load_settings()
    context = ServerContext()
    stop_event = threading.Event()

    # Warn about removed BACKUP_RETENTION
    if "BACKUP_RETENTION" in environ:
        logger.warning("BACKUP_RETENTION is ignored. Use BACKUP_KEEP_LAST, BACKUP_KEEP_DAILY, etc. instead.")

    _setup_timezone()
    _setup_directories()
    _setup_x11_socket()
    _ensure_wineprefix()

    install.prepare_manifests()
    target = install.ensure_install(force=install.get_force_install())

    mods.build_game_tree(target.name, puid=settings.puid, pgid=settings.pgid)
    new_config = config.generate_config()
    config.write_config(new_config, puid=settings.puid, pgid=settings.pgid)

    handler = _make_sigterm_handler(context)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    cron_expr = environ.get("BACKUP_CRON", DEFAULT_CRON)
    if is_truthy("BACKUP_LIVE", default=True):
        scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            args=(cron_expr,),
            daemon=True,
        )
        scheduler_thread.start()
    else:
        logger.info("Live backups disabled (BACKUP_LIVE=%s)", environ.get("BACKUP_LIVE", ""))

    context.server_process = _start_server()

    pid = context.server_process.pid
    PIDFILE.write_text(str(pid))
    logger.info("Server PID %s written to %s", pid, PIDFILE)

    log_thread: threading.Thread | None = None
    if is_truthy("LOG_TAIL", default=False):
        log_thread = _start_log_tail_thread(stop_event)

    _resource_thread = start_resource_poller(pid, stop_event, interval=settings.resource_poll_interval)

    _stream_output(context.server_process)

    exit_code = context.server_process.wait()
    logger.info("Server process exited with code %d", exit_code)
    stop_event.set()

    if log_thread is not None:
        log_thread.join(timeout=5)

    if not context.shutdown_requested:
        logger.error("Server exited unexpectedly (code %d)", exit_code)
        _cleanup_wineserver()
        if is_truthy("BACKUP_EMERGENCY", default=True) and backup.backup_needed():
            logger.info("Creating emergency backup")
            _run_backup(["--emergency"])
        PIDFILE.unlink(missing_ok=True)
        sys.exit(exit_code)
