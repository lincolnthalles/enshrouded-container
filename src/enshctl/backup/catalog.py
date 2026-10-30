"""Backup catalog — filename grammar, discovery, and selection.

Single home for what a Backup is and how to find one. All callers
(retention, verify, restore, backup runner) discover backups through
this interface instead of re-implementing directory scans.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePath

from enshctl.backup.category import CATEGORIES, Category
from enshctl.backup.format import ARCHIVE_EXTENSIONS, ARCHIVE_SUFFIXES, BackupFormat, detect_format

logger = logging.getLogger(__name__)

_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
_CATEGORY_SUFFIXES: dict[Category, str] = {
    Category.LIVE: "",
    Category.COLD: "-cold",
    Category.EMERGENCY: "-emergency",
}
_SUFFIX_CATEGORIES: dict[str, Category] = {
    suffix: category for category, suffix in _CATEGORY_SUFFIXES.items() if suffix
}
_SUFFIX_PATTERN = "|".join(re.escape(suffix) for suffix in _SUFFIX_CATEGORIES)
_EXTENSION_PATTERN = "|".join(re.escape(extension) for extension in ARCHIVE_EXTENSIONS)
_FILENAME_RE = re.compile(rf"^enshrouded-(\d{{8}}-\d{{6}})({_SUFFIX_PATTERN})?(?:{_EXTENSION_PATTERN})$")


@dataclass(frozen=True)
class BackupName:
    timestamp: datetime
    category: Category
    fmt: BackupFormat

    def __post_init__(self) -> None:
        """Coerce raw strings into their enum types and drop sub-second precision."""
        object.__setattr__(self, "timestamp", self.timestamp.replace(microsecond=0))
        object.__setattr__(self, "category", Category(self.category))
        object.__setattr__(self, "fmt", BackupFormat(self.fmt))

    def to_filename(self) -> str:
        suffix = _CATEGORY_SUFFIXES[self.category]
        return f"enshrouded-{self.timestamp.strftime(_TIMESTAMP_FORMAT)}{suffix}{self.fmt.get_extension()}"

    @classmethod
    def from_filename(cls, filename: str) -> BackupName | None:
        match = _FILENAME_RE.match(filename)
        if match is None:
            return None
        timestamp_raw, suffix = match.groups()
        try:
            timestamp = datetime.strptime(timestamp_raw, _TIMESTAMP_FORMAT).astimezone()
        except ValueError:
            return None
        category = _SUFFIX_CATEGORIES.get(suffix or "", Category.LIVE)
        try:
            fmt = detect_format(Path(filename))
        except ValueError:
            return None
        return cls(timestamp=timestamp, category=category, fmt=fmt)

    @classmethod
    def now(cls, category: Category, fmt: BackupFormat) -> BackupName:
        return cls(timestamp=_local_now(), category=category, fmt=fmt)


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    name: BackupName
    size: int


def _local_tz() -> timezone:
    """Return the local timezone offset currently in effect (respects TZ)."""
    is_dst = time.localtime().tm_isdst > 0
    offset = time.altzone if is_dst else time.timezone
    return timezone(timedelta(seconds=-offset))


def _local_now() -> datetime:
    """Return current time in the container's local timezone."""
    return datetime.now(_local_tz())


def scan_dir(category_dir: Path) -> list[BackupInfo]:
    """List backups in one category directory, newest first."""
    if not category_dir.exists():
        return []
    backups: list[BackupInfo] = []
    for p in sorted(category_dir.iterdir(), key=lambda x: x.name):
        if not p.is_file():
            continue
        name = BackupName.from_filename(p.name)
        if name is None:
            continue
        backups.append(BackupInfo(path=p, name=name, size=p.stat().st_size))
    backups.sort(key=lambda bi: bi.name.timestamp, reverse=True)
    return backups


def scan_all(base_dir: Path, category: Category | None = None, when: timedelta | None = None) -> list[BackupInfo]:
    """List backups across categories, newest first, optionally filtered."""
    results: list[BackupInfo] = []
    categories = [category] if category is not None else list(CATEGORIES)
    cutoff = _local_now() - when if when is not None else None
    for cat in categories:
        for info in scan_dir(base_dir / cat):
            if cutoff is not None and info.name.timestamp < cutoff:
                continue
            results.append(info)
    results.sort(key=lambda bi: bi.name.timestamp, reverse=True)
    return results


def scan_stray(base_dir: Path, category: Category | None = None) -> list[Path]:
    """List archive files that do not match the backup filename grammar, sorted by name."""
    results: list[Path] = []
    categories = [category] if category is not None else list(CATEGORIES)
    for cat in categories:
        cat_dir = base_dir / cat
        if not cat_dir.exists():
            continue
        for p in sorted(cat_dir.iterdir(), key=lambda x: x.name):
            if not p.is_file() or BackupName.from_filename(p.name) is not None:
                continue
            if p.suffix in ARCHIVE_SUFFIXES:
                results.append(p)
    return results


def select(base_dir: Path, file: str | None = None, when: str | None = None) -> Path | None:
    """Select a backup by filename or `--when` direction grammar."""
    if file:
        if PurePath(file).is_absolute() or ".." in PurePath(file).parts:
            return None
        for cat in CATEGORIES:
            candidate = base_dir / cat / file
            if candidate.is_file():
                return candidate
        return None

    if when:
        category: Category | None = None
        direction = when

        if ":" in when:
            direction, raw_category = when.split(":", 1)
            if raw_category:
                try:
                    category = Category(raw_category)
                except ValueError:
                    return None

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
            if value < 0:
                return None
            try:
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
            except OverflowError:
                return None

        try:
            backups = scan_all(base_dir, category=category, when=delta)
        except OverflowError:
            return None
        if backups:
            return backups[0].path
    return None
