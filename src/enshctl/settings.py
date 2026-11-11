"""Typed settings seam — immutable values, one environment loader, and the backup child contract."""

from dataclasses import MISSING, dataclass, field, fields, replace
from os import environ
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from dataclasses import Field

    type _Parser = Callable[[str, object], object]


def normalize_api_url(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


def _parse_int(raw: str, default: object) -> object:
    try:
        return int(raw)
    except ValueError, TypeError:
        return default


def _parse_non_negative_int(raw: str, default: object) -> object:
    try:
        return max(0, int(raw))
    except ValueError, TypeError:
        return default


def _parse_bool(raw: str, default: object) -> object:
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "on", "yes"):
        return True
    if normalized in ("0", "false", "off", "no"):
        return False
    return default


def _parse_str(raw: str, _default: object) -> str:
    return raw.strip()


def _parse_version(raw: str, _default: object) -> str:
    return raw.strip().lower()


def _parse_optional_str(raw: str, _default: object) -> str | None:
    value = raw.strip()
    return value or None


def _parse_unstripped(raw: str, _default: object) -> str:
    return raw


def _parse_csv(raw: str, _default: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_url(raw: str, _default: object) -> str | None:
    return normalize_api_url(raw)


def _env_field[T](default: T, key: str, parse: _Parser) -> T:
    return cast("T", field(default=default, metadata={"env_key": key, "parse": parse}))


@dataclass(frozen=True)
class AppSettings:
    """Typed, immutable settings values.

    Direct construction yields the documented defaults. Use `load_settings`
    for values read from an environment mapping.
    """

    # Identity
    puid: int = _env_field(1000, "PUID", _parse_int)
    pgid: int = _env_field(1000, "PGID", _parse_int)

    # Version / install
    version: str = _env_field("latest", "VERSION", _parse_version)
    force_install: bool = _env_field(default=False, key="FORCE_INSTALL", parse=_parse_bool)
    manifest_prune_enabled: bool = _env_field(default=True, key="MANIFEST_PRUNE_ENABLED", parse=_parse_bool)
    min_free_space: int = _env_field(10 * 1024**3, "INSTALL_MIN_FREE_SPACE", _parse_int)

    # Auto Update
    auto_update_enabled: bool = _env_field(default=True, key="AUTO_UPDATE_ENABLED", parse=_parse_bool)
    auto_update_cron: str = _env_field("*/60 * * * *", "AUTO_UPDATE_CRON", _parse_str)
    auto_update_log_only: bool = _env_field(default=False, key="AUTO_UPDATE_LOG_ONLY", parse=_parse_bool)
    auto_update_download_only_when_empty: bool = _env_field(
        default=False,
        key="AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY",
        parse=_parse_bool,
    )

    # ManifestHub / depot keys
    manifesthub_api_token: str | None = _env_field(None, "MANIFESTHUB_API_TOKEN", _parse_optional_str)
    manifesthub_api_url: str | None = _env_field(None, "MANIFESTHUB_API_URL", _parse_url)
    depot_keys_repo: str | None = _env_field(None, "DEPOT_KEYS_REPO", _parse_optional_str)

    # Steam auth
    steam_username: str | None = _env_field(None, "STEAM_USERNAME", _parse_optional_str)
    steam_password: str | None = _env_field(None, "STEAM_PASSWORD", _parse_optional_str)

    # Backup
    backup_dir: str = _env_field("/data/backups", "BACKUP_DIR", _parse_str)
    backup_format: str = _env_field("zstd", "BACKUP_FORMAT", _parse_str)
    backup_level: int | None = _env_field(None, "BACKUP_LEVEL", _parse_int)
    backup_cron: str = _env_field("*/60 * * * *", "BACKUP_CRON", _parse_str)
    backup_min_free_warn: int = _env_field(2 * 1024**3, "BACKUP_MIN_FREE_SPACE_WARN", _parse_int)
    backup_min_free_stop: int = _env_field(1 * 1024**3, "BACKUP_MIN_FREE_SPACE_STOP", _parse_int)
    backup_live: bool = _env_field(default=True, key="BACKUP_LIVE", parse=_parse_bool)
    backup_cold: bool = _env_field(default=True, key="BACKUP_COLD", parse=_parse_bool)
    backup_emergency: bool = _env_field(default=True, key="BACKUP_EMERGENCY", parse=_parse_bool)
    backup_exclude: str = _env_field("migrated/**;backup/world0.ksd.backup-[1-9]", "BACKUP_EXCLUDE", _parse_str)

    # Auto Rollback
    rollback_enabled: bool = _env_field(default=False, key="ROLLBACK_ENABLED", parse=_parse_bool)
    rollback_file: str = _env_field("", "ROLLBACK_FILE", _parse_str)
    rollback_cron: str = _env_field("", "ROLLBACK_CRON", _parse_str)

    # Logging / monitoring
    log_tail: bool = _env_field(default=False, key="LOG_TAIL", parse=_parse_bool)
    resource_poll_interval: int = _env_field(60, "RESOURCE_POLL_INTERVAL", _parse_int)
    player_log: bool = _env_field(default=True, key="PLAYER_LOG", parse=_parse_bool)
    player_poll_interval: int = _env_field(60, "PLAYER_POLL_INTERVAL", _parse_non_negative_int)

    # Auto Pause
    auto_pause_enabled: bool = _env_field(default=False, key="AUTO_PAUSE_ENABLED", parse=_parse_bool)
    auto_pause_idle_timeout: int = _env_field(300, "AUTO_PAUSE_IDLE_TIMEOUT", _parse_non_negative_int)

    # Shutdown
    shutdown_timeout: int = _env_field(60, "SHUTDOWN_TIMEOUT", _parse_non_negative_int)
    shutdown_backup_wait: int = _env_field(120, "SHUTDOWN_BACKUP_WAIT", _parse_non_negative_int)

    # Orchestrator logging
    orchestrator_log_file: str = _env_field("", "ORCHESTRATOR_LOG_FILE", _parse_str)
    orchestrator_log_level: str = _env_field("WARNING", "ORCHESTRATOR_LOG_LEVEL", _parse_str)

    # Wine / runtime
    winearch: str = _env_field("win64", "WINEARCH", _parse_str)
    winedebug: str = _env_field("fixme-all", "WINEDEBUG", _parse_str)
    winedlloverrides: str | None = _env_field(None, "WINEDLLOVERRIDES", _parse_unstripped)
    home: str = _env_field("/home/steam", "HOME", _parse_str)
    tz: str = _env_field("UTC", "TZ", _parse_str)

    # Mods / persistence
    persist_files: tuple[str, ...] = _env_field((), "PERSIST_FILES", _parse_csv)

    # Retention
    backup_keep_last: int = _env_field(24, "BACKUP_KEEP_LAST", _parse_int)
    backup_keep_hourly: int = _env_field(0, "BACKUP_KEEP_HOURLY", _parse_int)
    backup_keep_daily: int = _env_field(0, "BACKUP_KEEP_DAILY", _parse_int)
    backup_keep_weekly: int = _env_field(0, "BACKUP_KEEP_WEEKLY", _parse_int)
    backup_keep_monthly: int = _env_field(0, "BACKUP_KEEP_MONTHLY", _parse_int)
    backup_keep_yearly: int = _env_field(0, "BACKUP_KEEP_YEARLY", _parse_int)


def _env_key(settings_field: Field[object]) -> str | None:
    key = settings_field.metadata.get("env_key")
    return key if isinstance(key, str) else None


_BACKUP_CHILD_ENV_KEYS: tuple[str, ...] = tuple(
    key
    for settings_field in fields(AppSettings)
    if (key := _env_key(settings_field)) is not None and (key.startswith("BACKUP_") or key in ("PUID", "PGID"))
)


def load_settings(source: Mapping[str, str] | None = None) -> AppSettings:
    """Read one environment mapping and return a frozen settings object.

    Uses the process environment when `source` is omitted. Every env-backed
    field declares a plain default; `dataclasses.MISSING` means a field
    bypassed `_env_field` and is treated as a programming error.
    """
    env = environ if source is None else source
    changes: dict[str, Any] = {}
    for settings_field in fields(AppSettings):
        if settings_field.default is MISSING:
            msg = f"Settings field {settings_field.name} must declare a plain default"
            raise TypeError(msg)
        key = _env_key(settings_field)
        if key is None or key not in env:
            continue
        parse = cast("_Parser", settings_field.metadata["parse"])
        changes[settings_field.name] = parse(env[key], settings_field.default)
    return replace(AppSettings(), **changes)


def backup_child_env(source: Mapping[str, str]) -> dict[str, str]:
    """Return the declared settings-bearing environment the backup child inherits.

    Only declared `BACKUP_*`, `PUID`, and `PGID` settings cross the seam;
    unknown environment keys are excluded.
    """
    return {key: source[key] for key in _BACKUP_CHILD_ENV_KEYS if key in source}
