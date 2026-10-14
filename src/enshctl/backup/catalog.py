"""Backup catalog — filename grammar, discovery, and selection.

Single home for what a backup is and how to find one. All callers
(retention, verify, restore, backup runner) discover backups through
this interface instead of re-implementing directory scans.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from enshctl.settings import BACKUP_DIRS

if TYPE_CHECKING:
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


class BackupFormat(Enum):
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


def scan_dir(category_dir: Path) -> list[BackupInfo]:
    """List backups in one category directory, newest first."""
    if not category_dir.exists():
        return []
    backups: list[BackupInfo] = []
    for p in sorted(category_dir.iterdir(), key=lambda x: x.name):
        if not p.is_file():
            continue
        parsed = parse_backup_filename(p.name)
        if parsed is None:
            continue
        ts, cat, fmt = parsed
        backups.append(BackupInfo(path=p, timestamp=ts, category=cat, fmt=fmt, size=p.stat().st_size))
    backups.sort(key=lambda bi: bi.timestamp, reverse=True)
    return backups


def scan_all(base_dir: Path, category: str | None = None, when: timedelta | None = None) -> list[BackupInfo]:
    """List backups across categories, newest first, optionally filtered."""
    results: list[BackupInfo] = []
    categories = [category] if category else list(BACKUP_DIRS)
    cutoff = _local_now() - when if when else None
    for cat in categories:
        for info in scan_dir(base_dir / cat):
            if cutoff is not None and info.timestamp < cutoff:
                continue
            results.append(info)
    results.sort(key=lambda bi: bi.timestamp, reverse=True)
    return results


def select(base_dir: Path, file: str | None = None, when: str | None = None) -> Path | None:
    """Select a backup by filename or `--when` direction grammar."""
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

        if not direction:
            return None
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

        backups = scan_all(base_dir, category=category, when=delta)
        if backups:
            return backups[0].path

    return None


list_backups = scan_all


def select_backup(file: str | None = None, when: str | None = None, *, settings: AppSettings) -> Path | None:
    return select(Path(settings.backup_dir), file=file, when=when)
