"""Wine environment policy and prefix lifecycle."""

import logging
import subprocess
from typing import TYPE_CHECKING

from enshctl import mods
from enshctl.lifecycle.env import base_env
from enshctl.paths import WINE_PREFIX, WINE_PREFIX_INIT_MARKER, WINE_SERVER_BIN

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


def _env(
    settings: AppSettings,
    dll_overrides: str,
    *,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return {
        **base_env(source),
        "WINEPREFIX": f"{WINE_PREFIX}",
        "WINEARCH": settings.winearch,
        "WINEDEBUG": settings.winedebug,
        "HOME": settings.home,
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "WINEDLLOVERRIDES": dll_overrides,
        "XDG_RUNTIME_DIR": f"/var/run/user/{settings.puid}",
    }


def server_env(
    settings: AppSettings,
    *,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Full game-server environment with DLL overrides resolved at launch time."""
    return _env(settings, mods.resolve_dll_overrides(settings), source=source)


def tool_env(
    settings: AppSettings,
    *,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return _env(settings, mods.DEFAULT_DLL_OVERRIDES, source=source)


def cleanup(settings: AppSettings, *, wineserver_path: Path = WINE_SERVER_BIN) -> None:
    env = tool_env(settings)
    if wineserver_path.exists():
        logger.info("Cleaning up Wine server")
        try:
            subprocess.run(
                ["/usr/bin/runuser", "-u", "steam", "--", f"{wineserver_path}", "-k"],
                env=env,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Wine server cleanup timed out, forcing with -k9")
            try:
                subprocess.run(
                    ["/usr/bin/runuser", "-u", "steam", "--", f"{wineserver_path}", "-k9"],
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


def ensure_prefix(
    settings: AppSettings,
    *,
    marker_path: Path = WINE_PREFIX_INIT_MARKER,
    wineserver_path: Path = WINE_SERVER_BIN,
) -> None:
    """Initialize the Wine prefix if its completion marker is absent.

    Runs as the steam user so all prefix files have correct ownership.
    """
    if marker_path.exists():
        logger.info("Wine prefix already initialized")
        return

    cleanup(settings, wineserver_path=wineserver_path)

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
            env=tool_env(settings),
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
        marker_path.touch()
