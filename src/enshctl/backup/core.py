"""Backup orchestration, config, listing, selection, and cron parsing."""

import enum
import logging
import os
import re
import shutil
import time
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import zstandard

from enshctl.settings import (
    BACKUP_BASE_DIR,
    BACKUP_DIRS,
    SAVE_DIR,
)

logger = logging.getLogger(__name__)

DEFAULT_FORMAT = "zstd"

DEFAULT_MIN_FREE_WARN = 2 * 1024**3
DEFAULT_MIN_FREE_STOP = 1 * 1024**3


class BackupFormat(enum.Enum):
    ZSTD = "zstd"
    GZIP = "gzip"
    ZIP = "zip"

    def get_extension(self) -> str:
        match self:
            case BackupFormat.ZSTD:
                return ".tar.zst"
            case BackupFormat.GZIP:
                return ".tar.gz"
            case BackupFormat.ZIP:
                return ".zip"

    def get_max_level(self) -> int:
        match self:
            case BackupFormat.ZSTD:
                return 22
            case BackupFormat.GZIP:
                return 9
            case BackupFormat.ZIP:
                return 9

    def clamp_level(self, level: int) -> int:
        max_level = self.get_max_level()
        if level > max_level:
            logger.warning(
                "Compression level %d exceeds %s max (%d), clamping to %d", level, self.value, max_level, max_level
            )
            return max_level
        return level

    def get_default_level(self) -> int:
        match self:
            case BackupFormat.ZSTD:
                return 9
            case BackupFormat.GZIP:
                return 6
            case BackupFormat.ZIP:
                return 6


_FILENAME_RE = re.compile(r"^enshrouded-(\d{8})-(\d{6})(-cold|-emergency)?\.(tar\.zst|tar\.gz|zip)$")

_CATEGORY_SUFFIX_MAP: dict[str, str] = {
    "-cold": "cold",
    "-emergency": "emergency",
}

_FORMAT_EXTENSION_MAP: dict[str, BackupFormat] = {
    ".tar.zst": BackupFormat.ZSTD,
    ".tar.gz": BackupFormat.GZIP,
    ".zip": BackupFormat.ZIP,
}


@dataclass
class BackupInfo:
    path: Path
    timestamp: datetime
    category: str
    fmt: BackupFormat
    size: int


def get_min_free_warn() -> int:
    try:
        return int(os.environ.get("BACKUP_MIN_FREE_SPACE_WARN", str(DEFAULT_MIN_FREE_WARN)))
    except (ValueError, TypeError):
        return DEFAULT_MIN_FREE_WARN


def get_min_free_stop() -> int:
    try:
        return int(os.environ.get("BACKUP_MIN_FREE_SPACE_STOP", str(DEFAULT_MIN_FREE_STOP)))
    except (ValueError, TypeError):
        return DEFAULT_MIN_FREE_STOP


def _local_tz() -> timezone:
    """Return the container's local timezone (respects TZ env var)."""
    offset = time.timezone if time.daylight == 0 else time.altzone
    return timezone(timedelta(seconds=-offset))


def _local_now() -> datetime:
    """Return current time in the container's local timezone."""
    return datetime.now(_local_tz())


def parse_backup_filename(filename: str) -> tuple[datetime, str, BackupFormat] | None:
    """Parse an `enshrouded-YYYYMMDD-HHMMSS[-cold|-emergency].<ext>` filename.

    Returns (timestamp, category, format) or None if the filename doesn't match.
    """
    m = _FILENAME_RE.match(filename)
    if not m:
        return None
    date_str, time_str, suffix, ext = m.groups()
    try:
        ts = datetime(
            int(date_str[:4]),
            int(date_str[4:6]),
            int(date_str[6:8]),
            int(time_str[:2]),
            int(time_str[2:4]),
            int(time_str[4:6]),
            tzinfo=_local_tz(),
        )
    except ValueError:
        return None
    category = _CATEGORY_SUFFIX_MAP.get(suffix or "", "live")
    fmt = _FORMAT_EXTENSION_MAP[f".{ext}"]
    return ts, category, fmt


def human_size(size: float) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", str(BACKUP_BASE_DIR)))


def backup_needed() -> bool:
    if not SAVE_DIR.exists():
        return False
    try:
        return any(SAVE_DIR.iterdir())
    except OSError:
        return False


def get_format() -> BackupFormat:
    raw = os.environ.get("BACKUP_FORMAT", DEFAULT_FORMAT).lower()
    try:
        return BackupFormat(raw)
    except ValueError:
        logger.warning("Unknown BACKUP_FORMAT '%s', falling back to zstd", raw)
        return BackupFormat.ZSTD


def get_level(fmt: BackupFormat) -> int:
    raw = os.environ.get("BACKUP_LEVEL", "")
    if raw:
        try:
            level = int(raw)
        except (ValueError, TypeError):
            level = fmt.get_default_level()
        return fmt.clamp_level(level)
    return fmt.get_default_level()


def create_backup(category: str = "live") -> Path | None:
    from enshctl.backup.archive import _compress_gzip, _compress_zip, _compress_zstd  # noqa: PLC0415

    if not backup_needed():
        logger.info("Save directory empty or missing, skipping backup")
        return None

    backup_dir = get_backup_dir() / category
    backup_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(backup_dir).free
    min_free_stop = get_min_free_stop()
    min_free_warn = get_min_free_warn()
    if free < min_free_stop:
        logger.warning(
            "Disk space critical: %s free (minimum %s), skipping backup",
            human_size(free),
            human_size(min_free_stop),
        )
        return None
    if free < min_free_warn:
        logger.warning("Disk space low: %s free (warning threshold %s)", human_size(free), human_size(min_free_warn))

    fmt = get_format()
    level = get_level(fmt)
    timestamp = _local_now().strftime("%Y%m%d-%H%M%S")

    suffix = ""
    if category == "cold":
        suffix = "-cold"
    elif category == "emergency":
        suffix = "-emergency"

    ext = fmt.get_extension()
    filename = f"enshrouded-{timestamp}{suffix}{ext}"
    output_path = backup_dir / filename

    compressors = {
        BackupFormat.ZSTD: _compress_zstd,
        BackupFormat.GZIP: _compress_gzip,
        BackupFormat.ZIP: _compress_zip,
    }

    compress = compressors[fmt]

    try:
        compress(SAVE_DIR, output_path, level)
    except (OSError, zstandard.ZstdError, zipfile.BadZipFile) as exc:
        logger.warning("Backup failed for %s: %s", output_path, exc)
        with suppress(OSError):
            output_path.unlink()
        return None
    else:
        logger.info("Backup created: %s", output_path)
        return output_path


def list_backups(base_dir: Path, category: str | None = None, when: timedelta | None = None) -> list[BackupInfo]:
    results: list[BackupInfo] = []
    categories = [category] if category else list(BACKUP_DIRS)
    cutoff = _local_now() - when if when else None

    for cat in categories:
        cat_dir = base_dir / cat
        if not cat_dir.exists():
            continue
        for p in sorted(cat_dir.iterdir(), key=lambda x: x.name):
            if not p.is_file():
                continue
            parsed = parse_backup_filename(p.name)
            if parsed is None:
                continue
            ts, parsed_cat, fmt = parsed
            if cutoff is not None and ts < cutoff:
                continue
            results.append(BackupInfo(path=p, timestamp=ts, category=parsed_cat, fmt=fmt, size=p.stat().st_size))

    results.sort(key=lambda bi: bi.timestamp, reverse=True)
    return results


def select_backup(file: str | None = None, when: str | None = None) -> Path | None:
    base_dir = get_backup_dir()

    if file:
        for cat in BACKUP_DIRS:
            candidate = base_dir / cat / file
            if candidate.exists():
                return candidate
        return None

    if when:
        category: str | None = None
        direction = when

        if ":" in when:
            direction, category = when.split(":", 1)
            if not category:
                category = None

        if direction == "last":
            delta: timedelta | None = None
        else:
            unit = direction[-1]
            try:
                value = int(direction[:-1])
            except ValueError:
                return None
            match unit:
                case "m":
                    delta = timedelta(minutes=value)
                case "h":
                    delta = timedelta(hours=value)
                case "d":
                    delta = timedelta(days=value)
                case "M":
                    delta = timedelta(days=value * 30)
                case _:
                    return None

        backups = list_backups(base_dir, category=category, when=delta)
        if backups:
            return backups[0].path

    return None


def parse_cron(expr: str) -> float | None:
    """Parse a cron expression to seconds until next trigger. Supports '*/N' syntax."""
    parts = expr.strip().split()
    if len(parts) != 5:
        logger.error("Invalid cron expression: %s", expr)
        return None

    minute_part, hour_part, day_part, month_part, weekday_part = parts
    unsupported = []
    if hour_part != "*":
        unsupported.append(f"hour={hour_part}")
    if day_part != "*":
        unsupported.append(f"day={day_part}")
    if month_part != "*":
        unsupported.append(f"month={month_part}")
    if weekday_part != "*":
        unsupported.append(f"weekday={weekday_part}")
    if unsupported:
        logger.warning(
            "Cron expression has unsupported fields (%s); only minute-level scheduling is supported. "
            "Ignoring non-minute fields.",
            ", ".join(unsupported),
        )

    if minute_part.startswith("*/"):
        with suppress(ValueError):
            interval = int(minute_part[2:])
            now = time.localtime()
            remaining = (interval - now.tm_min % interval) * 60 - now.tm_sec
            return float(max(remaining, 60))

    if minute_part.isdigit():
        with suppress(ValueError):
            target_min = int(minute_part)
            now = time.localtime()
            current_min = now.tm_min
            remaining = (target_min - current_min) % 60
            if remaining == 0:
                remaining = 60
            return float(remaining * 60)

    logger.warning("Unsupported cron expression, defaulting to 20 minutes: %s", expr)
    return 1200.0
