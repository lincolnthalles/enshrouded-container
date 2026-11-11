"""Backup content filter — exclude-list for saves-tree members.

Deep module: callers learn one small interface (`BackupExcludes.from_raw`
plus `is_excluded`), while pattern normalization, validation, and `/**`
pruning stay inside.
"""

import logging
from dataclasses import dataclass
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)


def _parse_raw(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(";") if part.strip())


def _is_valid_pattern(pattern: str) -> bool:
    if pattern.startswith("/"):
        return False
    if pattern in {"", ".", "./"}:
        return False
    parts = pattern.split("/")
    if ".." in parts:
        return False
    try:
        PurePosixPath("probe").full_match(pattern)
    except ValueError:
        return False
    return True


def _matches(rel: PurePosixPath, pattern: str) -> bool:
    if pattern == "**":
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if not prefix:
            return True
        try:
            return rel.full_match(prefix) or rel.full_match(pattern)
        except ValueError:
            return False
    try:
        return rel.full_match(pattern)
    except ValueError:
        return False


@dataclass(frozen=True)
class BackupExcludes:
    patterns: tuple[str, ...] = ()

    @classmethod
    def from_raw(cls, raw: str) -> BackupExcludes:
        valid: list[str] = []
        for raw_pattern in _parse_raw(raw):
            if raw_pattern.startswith("/"):
                logger.warning("Ignoring invalid BACKUP_EXCLUDE pattern '%s'", raw_pattern)
                continue
            pattern = raw_pattern
            while pattern.startswith("./"):
                pattern = pattern[2:]
            pattern = pattern.rstrip("/")
            if not _is_valid_pattern(pattern):
                logger.warning("Ignoring invalid BACKUP_EXCLUDE pattern '%s'", raw_pattern)
                continue
            valid.append(pattern)
        return cls(patterns=tuple(valid))

    def is_excluded(self, rel: str | PurePosixPath) -> bool:
        text = str(rel).replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        text = text.lstrip("/").rstrip("/")
        if not text or text == ".":
            return False
        candidate = PurePosixPath(text)
        for parent in (candidate, *candidate.parents):
            if str(parent) in {"", "."}:
                continue
            if any(_matches(parent, pattern) for pattern in self.patterns):
                return True
        return False
