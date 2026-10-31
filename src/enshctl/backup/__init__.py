"""Save world backup system with multi-format compression, file locking, and retention."""

from enshctl.backup.catalog import (
    BackupInfo,
    BackupName,
    scan_all,
    scan_dir,
    scan_stray,
    select,
)
from enshctl.backup.category import CATEGORIES, Category
from enshctl.backup.core import (
    backup_needed,
    create_backup,
    resolve_format,
    resolve_level,
)
from enshctl.backup.format import (
    ArchiveError,
    BackupFormat,
    decompress_archive,
    verify_archive,
)
from enshctl.backup.locking import (
    LOCK_FILE,
    acquire_lock,
    release_lock,
)

__all__ = [
    "CATEGORIES",
    "LOCK_FILE",
    "ArchiveError",
    "BackupFormat",
    "BackupInfo",
    "BackupName",
    "Category",
    "acquire_lock",
    "backup_needed",
    "create_backup",
    "decompress_archive",
    "release_lock",
    "resolve_format",
    "resolve_level",
    "scan_all",
    "scan_dir",
    "scan_stray",
    "select",
    "verify_archive",
]
