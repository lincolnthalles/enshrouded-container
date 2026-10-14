"""Save world backup system with multi-format compression, file locking, and retention."""

import importlib
from typing import Any

from enshctl.backup.archive import (
    decompress_archive,
    verify_archive,
)
from enshctl.backup.catalog import (
    BackupInfo,
    _local_now,
    _local_tz,
    list_backups,
    parse_backup_filename,
    scan_all,
    scan_dir,
    scan_stray,
    select,
    select_backup,
)
from enshctl.backup.core import (
    BackupFormat,
    backup_needed,
    create_backup,
    resolve_format,
    resolve_level,
)
from enshctl.backup.locking import (
    LOCK_FILE,
    acquire_lock,
    release_lock,
)
from enshctl.settings import (
    BACKUP_DIR_COLD,
    BACKUP_DIR_EMERGENCY,
    BACKUP_DIR_LIVE,
    BACKUP_DIRS,
    SAVE_DIR,
)
from enshctl.utils import human_size

__all__ = [
    "BACKUP_DIRS",
    "BACKUP_DIR_COLD",
    "BACKUP_DIR_EMERGENCY",
    "BACKUP_DIR_LIVE",
    "LOCK_FILE",
    "SAVE_DIR",
    "BackupFormat",
    "BackupInfo",
    "_local_now",
    "_local_tz",
    "acquire_lock",
    "backup_needed",
    "create_backup",
    "decompress_archive",
    "human_size",
    "list_backups",
    "parse_backup_filename",
    "parse_cron",
    "release_lock",
    "resolve_format",
    "resolve_level",
    "scan_all",
    "scan_dir",
    "scan_stray",
    "select",
    "select_backup",
    "verify_archive",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "parse_cron": ("enshctl.commands.start", "parse_cron"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        module_name, attr = _LAZY_EXPORTS[name]
        value = getattr(importlib.import_module(module_name), attr)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
