"""Start subcommand — startup wiring for the server lifecycle."""

import logging
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from enshctl import mods, staging
from enshctl.commands.parser import CommandParser
from enshctl.files import chown_tree
from enshctl.lifecycle import ServerLifecycle
from enshctl.lifecycle.auto_update import is_auto_update_active
from enshctl.lifecycle.wine import ensure_prefix
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
from enshctl.staging import STARTUP_ERRORS, PreparedServer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from enshctl.download.types import ManifestRecord

logger = logging.getLogger(__name__)


class StageCallable(Protocol):
    """Callable that stages one Manifest selection."""

    def __call__(
        self,
        settings: AppSettings,
        *,
        target: ManifestRecord | None = None,
    ) -> PreparedServer: ...


class BuildLifecycle(Protocol):
    """Callable that constructs one Server lifecycle."""

    def __call__(
        self,
        settings: AppSettings,
        *,
        active_manifest: ManifestRecord,
        shutdown_event: threading.Event,
    ) -> ServerLifecycle: ...


@dataclass(frozen=True)
class StartupSeams:
    """Staging and lifecycle construction seams for one start invocation."""

    stage: StageCallable = staging.stage
    build_lifecycle: BuildLifecycle = ServerLifecycle


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


def run(
    settings: AppSettings | None = None,
    argv: Sequence[str] = (),
    *,
    seams: StartupSeams | None = None,
) -> int:
    """Run the start subcommand — setup wiring plus the server lifecycle."""
    _ = CommandParser("Start subcommand").parse(argv)
    settings = settings or load_settings()
    resolved = seams or StartupSeams()

    if "BACKUP_RETENTION" in environ:
        logger.warning("BACKUP_RETENTION is ignored. Use BACKUP_KEEP_LAST, BACKUP_KEEP_DAILY, etc. instead.")

    try:
        # Validate the roots before any setup I/O; the install entry is checked on the final plan.
        mods.GameTreePlan.from_settings("", settings)
        _setup_timezone(settings)
        _setup_directories(settings)
        _setup_x11_socket()
        ensure_prefix(settings)
        prepared = resolved.stage(settings)
    except STARTUP_ERRORS:
        logger.exception("Start failed")
        return 1

    if is_auto_update_active(settings) and mods.mod_files():
        logger.warning("Auto Update: mod files are present; automatic updates may break mods")

    shutdown_event = threading.Event()
    while True:
        lifecycle = resolved.build_lifecycle(
            settings,
            active_manifest=prepared.active_manifest,
            shutdown_event=shutdown_event,
        )
        exit_code = lifecycle.run()
        target = lifecycle.restart_manifest
        if not lifecycle.restart_requested or exit_code != 0:
            return exit_code
        if shutdown_event.is_set():
            return exit_code
        if target is None:
            logger.error("Auto Update: restart requested without a pending Manifest")
            return 1
        logger.info("Auto Update: relaunching with manifest %s", target.manifest_id)
        try:
            prepared = resolved.stage(settings, target=target)
        except STARTUP_ERRORS:
            logger.exception("Update restart failed")
            return 1
        if shutdown_event.is_set():
            return 0
