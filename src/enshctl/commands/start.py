"""Start subcommand — startup wiring for the server lifecycle."""

import logging
import subprocess
import time
from contextlib import suppress
from os import chown, environ
from pathlib import Path

from enshctl import config, download as download_flow, install, mods
from enshctl.download import InstallError
from enshctl.files import chown_tree
from enshctl.lifecycle import ServerLifecycle
from enshctl.lifecycle.process import ensure_wineprefix
from enshctl.paths import (
    BACKUP_BASE_DIR,
    CONFIG_DIR,
    LOG_DIR,
    MANIFESTS_DIR,
    MOD_OVERLAY_DIR,
    SAVE_DIR,
    WINE_PREFIX,
    X11_DIR,
)
from enshctl.settings import AppSettings, load_settings

logger = logging.getLogger(__name__)


def _setup_directories(settings: AppSettings) -> None:
    uid, gid = settings.puid, settings.pgid
    xdg_dir = f"/var/run/user/{uid}"
    dirs = [
        SAVE_DIR,
        LOG_DIR,
        BACKUP_BASE_DIR,
        MOD_OVERLAY_DIR,
        MANIFESTS_DIR,
        CONFIG_DIR,
        xdg_dir,
        WINE_PREFIX,
    ]

    logger.info("Recursively setting permissions for working directories under /data")
    logger.info("UID: %d, GID: %d", uid, gid)
    paths = (Path(str(p)) for p in dirs)
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            chown_tree(p, uid=uid, gid=gid)


def _setup_x11_socket() -> None:
    X11_DIR.mkdir(parents=True, exist_ok=True)
    X11_DIR.chmod(0o1777)


def _prepare_install_and_config(settings: AppSettings) -> None:
    download_flow.prepare_manifests(settings)
    installed = install.ensure_install(settings)

    plan = mods.GameTreePlan.from_settings(installed.name, settings)
    mods.build_game_tree(plan)
    saves_dir = config.write_generated_config(settings).saves_dir
    if saves_dir == SAVE_DIR:
        return
    saves_dir.mkdir(parents=True, exist_ok=True)
    ownership_failed = False
    for path in (saves_dir, *saves_dir.rglob("*")):
        try:
            chown(path, settings.puid, settings.pgid, follow_symlinks=False)
        except OSError as exc:
            if not ownership_failed:
                logger.warning("Could not set ownership on %s: %s", path, exc)
                ownership_failed = True


def _setup_timezone(settings: AppSettings) -> None:
    tz = settings.tz
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


def run(settings: AppSettings | None = None) -> int:
    """Run the start subcommand — setup wiring plus the server lifecycle."""
    settings = settings or load_settings()

    if "BACKUP_RETENTION" in environ:
        logger.warning("BACKUP_RETENTION is ignored. Use BACKUP_KEEP_LAST, BACKUP_KEEP_DAILY, etc. instead.")

    try:
        # Validate the roots before any setup I/O; the install entry is checked on the final plan.
        mods.GameTreePlan.from_settings("", settings)
        _setup_timezone(settings)
        _setup_directories(settings)
        _setup_x11_socket()
        ensure_wineprefix(settings)
        _prepare_install_and_config(settings)
    except InstallError, OSError, subprocess.SubprocessError, ValueError, mods.GameTreeError:
        logger.exception("Start failed")
        return 1

    return ServerLifecycle(settings).run()
