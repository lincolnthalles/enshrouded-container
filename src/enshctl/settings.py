"""Typed, immutable container for all env-var-derived configuration."""

from dataclasses import dataclass, field
from os import environ


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
    if not raw:
        return default
    if raw in ("1", "true", "on", "yes"):
        return True
    if raw in ("0", "false", "off", "no"):
        return False
    return default


def _env_optional_int(key: str) -> int | None:
    raw = environ.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_optional(key: str) -> str | None:
    val = environ.get(key, "").strip()
    return val or None


def normalize_api_url(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


def _env_str_list(key: str) -> tuple[str, ...]:
    raw = environ.get(key, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class AppSettings:
    """Typed, immutable container for all env-var-derived configuration."""

    # Identity
    puid: int = field(default_factory=lambda: _env_int("PUID", 1000))
    pgid: int = field(default_factory=lambda: _env_int("PGID", 1000))

    # Version / install
    version: str = field(default_factory=lambda: _env_str("VERSION", "latest").lower())
    force_install: bool = field(default_factory=lambda: _env_bool("FORCE_INSTALL", default=False))
    min_free_space: int = field(default_factory=lambda: _env_int("INSTALL_MIN_FREE_SPACE", 10 * 1024**3))

    # ManifestHub / depot keys
    manifesthub_api_token: str | None = field(default_factory=lambda: _env_optional("MANIFESTHUB_API_TOKEN"))
    manifesthub_api_url: str | None = field(
        default_factory=lambda: normalize_api_url(environ.get("MANIFESTHUB_API_URL"))
    )
    depot_keys_repo: str | None = field(default_factory=lambda: _env_optional("DEPOT_KEYS_REPO"))

    # Steam auth
    steam_username: str | None = field(default_factory=lambda: _env_optional("STEAM_USERNAME"))
    steam_password: str | None = field(default_factory=lambda: _env_optional("STEAM_PASSWORD"))

    # Backup
    backup_dir: str = field(default_factory=lambda: _env_str("BACKUP_DIR", "/data/backups"))
    backup_format: str = field(default_factory=lambda: _env_str("BACKUP_FORMAT", "zstd"))
    backup_level: int | None = field(default_factory=lambda: _env_optional_int("BACKUP_LEVEL"))
    backup_cron: str = field(default_factory=lambda: _env_str("BACKUP_CRON", "*/60 * * * *"))
    backup_min_free_warn: int = field(default_factory=lambda: _env_int("BACKUP_MIN_FREE_SPACE_WARN", 2 * 1024**3))
    backup_min_free_stop: int = field(default_factory=lambda: _env_int("BACKUP_MIN_FREE_SPACE_STOP", 1 * 1024**3))
    backup_live: bool = field(default_factory=lambda: _env_bool("BACKUP_LIVE", default=True))
    backup_cold: bool = field(default_factory=lambda: _env_bool("BACKUP_COLD", default=True))
    backup_emergency: bool = field(default_factory=lambda: _env_bool("BACKUP_EMERGENCY", default=True))

    # Logging / monitoring
    log_tail: bool = field(default_factory=lambda: _env_bool("LOG_TAIL", default=False))
    resource_poll_interval: int = field(default_factory=lambda: _env_int("RESOURCE_POLL_INTERVAL", 60))

    # Shutdown
    shutdown_timeout: int = field(default_factory=lambda: max(0, _env_int("SHUTDOWN_TIMEOUT", 60)))
    shutdown_backup_wait: int = field(
        default_factory=lambda: max(0, _env_int("SHUTDOWN_BACKUP_WAIT", 120))
    )

    # Orchestrator logging
    orchestrator_log_file: str = field(default_factory=lambda: _env_str("ORCHESTRATOR_LOG_FILE", ""))
    orchestrator_log_level: str = field(default_factory=lambda: _env_str("ORCHESTRATOR_LOG_LEVEL", "WARNING"))

    # Wine / runtime
    winearch: str = field(default_factory=lambda: _env_str("WINEARCH", "win64"))
    winedebug: str = field(default_factory=lambda: _env_str("WINEDEBUG", "fixme-all"))
    winedlloverrides: str | None = field(default_factory=lambda: environ.get("WINEDLLOVERRIDES"))
    home: str = field(default_factory=lambda: _env_str("HOME", "/home/steam"))
    tz: str = field(default_factory=lambda: _env_str("TZ", "UTC"))

    # Mods / persistence
    persist_files: tuple[str, ...] = field(default_factory=lambda: _env_str_list("PERSIST_FILES"))

    # Retention
    backup_keep_last: int = field(default_factory=lambda: _env_int("BACKUP_KEEP_LAST", 24))
    backup_keep_hourly: int = field(default_factory=lambda: _env_int("BACKUP_KEEP_HOURLY", 0))
    backup_keep_daily: int = field(default_factory=lambda: _env_int("BACKUP_KEEP_DAILY", 0))
    backup_keep_weekly: int = field(default_factory=lambda: _env_int("BACKUP_KEEP_WEEKLY", 0))
    backup_keep_monthly: int = field(default_factory=lambda: _env_int("BACKUP_KEEP_MONTHLY", 0))
    backup_keep_yearly: int = field(default_factory=lambda: _env_int("BACKUP_KEEP_YEARLY", 0))


def load_settings() -> AppSettings:
    """Read env vars once and return a frozen AppSettings instance."""
    return AppSettings()
