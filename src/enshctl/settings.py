"""Centralized configuration — single source of truth for path constants and env-var-derived settings."""

from dataclasses import dataclass, field
from os import environ
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants (immutable, no env-var dependency)
# ---------------------------------------------------------------------------

SAVE_DIR = Path("/data/saves")
LOG_DIR = Path("/data/logs")
MANIFESTS_DIR = Path("/data/manifests")
CONFIG_DIR = Path("/data/config")
MOUNT_POINT = Path("/data/gameserver")
BACKUP_BASE_DIR = Path("/data/backups")
WINE_PREFIX = Path("/data/wineprefix")
MODS_DIR = Path("/data/mods")
X11_DIR = Path("/tmp/.X11-unix")

GAME_EXE = MOUNT_POINT / "enshrouded_server.exe"
CONFIG_FILE = CONFIG_DIR / "enshrouded_server.json"
OUTPUT_CONFIG = CONFIG_DIR / "enshrouded_server.json"
GAME_CONFIG_EXAMPLE = MOUNT_POINT / "enshrouded_server_example.json"
PIDFILE = BACKUP_BASE_DIR / "enshctl.pid"
WINE_PREFIX_INIT_MARKER = WINE_PREFIX / ".wineboot-completed"
WINE_SERVER_BIN = Path("/usr/bin/wineserver")
DEPOT_KEYS_FILE = MANIFESTS_DIR / "depot.keys"
LATEST_MANIFEST_FILE = MANIFESTS_DIR / ".latest-manifest"
STATUS_FILE = ".installed"

RESTORE_TMP_DIR = SAVE_DIR.parent / "saves-restore-tmp"

APP_ID = "2278520"
DEPOT_ID = "2278521"
CONFIG_FILENAME = "enshrouded_server.json"
DEPOT_DOWNLOADER = ("/usr/bin/runuser", "-u", "steam", "--", "/opt/depotdownloader/DepotDownloader")
MANIFEST_TMP_DIR = "/tmp/depotdownloader"


# ---------------------------------------------------------------------------
# Backup category directories (tuple, immutable)
# ---------------------------------------------------------------------------

BACKUP_DIR_LIVE = "live"
BACKUP_DIR_COLD = "cold"
BACKUP_DIR_EMERGENCY = "emergency"
BACKUP_DIRS = (BACKUP_DIR_LIVE, BACKUP_DIR_COLD, BACKUP_DIR_EMERGENCY)


# ---------------------------------------------------------------------------
# AppSettings — frozen dataclass for all env-var-derived configuration
# ---------------------------------------------------------------------------


def _env_int(key: str, default: int) -> int:
    try:
        return int(environ.get(key, str(default)))
    except ValueError, TypeError:
        return default


def _env_str(key: str, default: str = "") -> str:
    return environ.get(key, default).strip()


def _env_float(key: str, default: float) -> float:
    try:
        return float(environ.get(key, str(default)))
    except ValueError, TypeError:
        return default


def _env_bool(key: str, *, default: bool) -> bool:
    raw = environ.get(key, "").lower().strip()
    if raw in ("", None):
        return default
    return raw in ("1", "true", "on", "yes")


def _env_optional(key: str) -> str | None:
    val = environ.get(key, "").strip()
    return val or None


@dataclass(frozen=True)
class AppSettings:
    """Typed, immutable container for all env-var-derived configuration."""

    # Identity
    puid: int = field(default_factory=lambda: _env_int("PUID", 1000))
    pgid: int = field(default_factory=lambda: _env_int("PGID", 1000))

    # Version / install
    version: str = field(default_factory=lambda: _env_str("VERSION", "latest"))
    force_install: bool = field(default_factory=lambda: _env_bool("FORCE_INSTALL", default=False))
    min_free_space: int = field(default_factory=lambda: _env_int("INSTALL_MIN_FREE_SPACE", 10 * 1024**3))

    # ManifestHub / depot keys
    manifesthub_api_token: str | None = field(default_factory=lambda: _env_optional("MANIFESTHUB_API_TOKEN"))
    manifesthub_api_url: str | None = field(default_factory=lambda: _env_optional("MANIFESTHUB_API_URL"))
    depot_keys_repo: str | None = field(default_factory=lambda: _env_optional("DEPOT_KEYS_REPO"))

    # Steam auth
    steam_username: str | None = field(default_factory=lambda: _env_optional("STEAM_USERNAME"))
    steam_password: str | None = field(default_factory=lambda: _env_optional("STEAM_PASSWORD"))

    # Backup
    backup_dir: str = field(default_factory=lambda: _env_str("BACKUP_DIR", "/data/backups"))
    backup_format: str = field(default_factory=lambda: _env_str("BACKUP_FORMAT", "zstd"))
    backup_level: int = field(default_factory=lambda: _env_int("BACKUP_LEVEL", 9))
    backup_cron: str = field(default_factory=lambda: _env_str("BACKUP_CRON", "*/60 * * * *"))
    backup_min_free_warn: int = field(default_factory=lambda: _env_int("BACKUP_MIN_FREE_SPACE_WARN", 2 * 1024**3))
    backup_min_free_stop: int = field(default_factory=lambda: _env_int("BACKUP_MIN_FREE_SPACE_STOP", 1 * 1024**3))
    backup_live: bool = field(default_factory=lambda: _env_bool("BACKUP_LIVE", default=True))
    backup_cold: bool = field(default_factory=lambda: _env_bool("BACKUP_COLD", default=True))
    backup_emergency: bool = field(default_factory=lambda: _env_bool("BACKUP_EMERGENCY", default=True))

    # Logging / monitoring
    log_tail: bool = field(default_factory=lambda: _env_bool("LOG_TAIL", default=False))
    resource_poll_interval: int = field(default_factory=lambda: _env_int("RESOURCE_POLL_INTERVAL", 60))

    # Orchestrator logging
    orchestrator_log_file: str = field(default_factory=lambda: _env_str("ORCHESTRATOR_LOG_FILE", ""))
    orchestrator_log_level: str = field(default_factory=lambda: _env_str("ORCHESTRATOR_LOG_LEVEL", "WARNING"))

    # Wine / runtime
    winearch: str = field(default_factory=lambda: _env_str("WINEARCH", "win64"))
    winedebug: str = field(default_factory=lambda: _env_str("WINEDEBUG", "fixme-all"))
    home: str = field(default_factory=lambda: _env_str("HOME", "/home/steam"))
    tz: str = field(default_factory=lambda: _env_str("TZ", "UTC"))


def load_settings() -> AppSettings:
    """Read env vars once and return a frozen AppSettings instance."""
    return AppSettings()
