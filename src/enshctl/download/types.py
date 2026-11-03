"""Download value types and the Install failure contract."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class InstallError(Exception):
    """Raised when game installation cannot be completed."""


@dataclass(frozen=True)
class DownloadConfig:
    """Strategy-specific parameters for DepotDownloader invocation."""

    username: str | None = None
    password: str | None = None
    use_manifestfile: bool = False
    depot_keys_path: Path | None = None
    manifest_file: Path | None = None
    use_qr: bool = False
    print_qr_message: bool = False
    timeout: int = 3600
    max_downloads: int = 8


@dataclass(frozen=True)
class ManifestRecord:
    """One Manifest reported by a DepotDownloader listing."""

    manifest_id: str
    timestamp: str
    branch: str = "public"


@dataclass(frozen=True)
class ManifestFile:
    """A Manifest file snapshot carrying any acquisition failure."""

    path: Path
    is_present: bool
    error: InstallError | None = None
