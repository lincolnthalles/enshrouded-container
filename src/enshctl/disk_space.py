"""Shared free-space guard for Install, Backup, and Restore."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from enshctl.files import disk_free_bytes, read_tree_size

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True)
class SpaceVerdict:
    """Space measured against a required byte count."""

    free_bytes: int
    existing_bytes: int
    required_bytes: int

    @property
    def available_bytes(self) -> int:
        return self.free_bytes + self.existing_bytes

    @property
    def shortfall_bytes(self) -> int:
        return max(0, self.required_bytes - self.available_bytes)

    @property
    def is_sufficient(self) -> bool:
        return self.shortfall_bytes == 0


@dataclass(frozen=True)
class SpaceGuard:
    """Measure free space and tree sizes through injectable probes."""

    disk_free: Callable[[Path], int] = disk_free_bytes
    tree_size: Callable[[Path], int] = read_tree_size

    def check(self, path: Path, *, required_bytes: int, existing_bytes: int = 0) -> SpaceVerdict:
        return SpaceVerdict(
            free_bytes=self.disk_free(path),
            existing_bytes=existing_bytes,
            required_bytes=required_bytes,
        )
