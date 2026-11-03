"""Server process control — launch, output streaming, and signaling."""

import logging
import subprocess
import threading
from typing import TYPE_CHECKING

from enshctl.lifecycle import gamelog, wine
from enshctl.paths import GAME_EXE

if TYPE_CHECKING:
    from collections.abc import Mapping

    from enshctl.lifecycle.types import ServerProcess
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


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


def stream(process: ServerProcess) -> threading.Thread:
    """Drain server stdout to the logger in a daemon thread."""

    def reader() -> None:
        try:
            if process.stdout is None:
                logger.warning("No server stdout to stream")
                return
            for line in iter(process.stdout.readline, b""):
                decoded = line.decode(errors="replace").rstrip()
                if decoded:
                    logger.log(gamelog.SERVER, decoded, extra={"source": "gameserver"})
            process.stdout.close()
        except OSError:
            logger.exception("Failed to read server output")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return thread


def signal(sig: int) -> bool:
    """Send a signal to the game server process tree, bypassing the runuser wrapper.

    Returns True if at least one signal was delivered.
    """
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

    delivered = result.returncode == 0
    if not delivered:
        logger.warning("No game server process matched for signal %d", sig)
    return delivered
