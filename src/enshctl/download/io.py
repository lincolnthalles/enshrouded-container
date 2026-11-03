"""Install I/O seams — host operations and DepotDownloader/ManifestHub operations."""

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from enshctl import files, hub, keys
from enshctl.disk_space import SpaceGuard
from enshctl.download.depotdownloader import DepotDownloader

if TYPE_CHECKING:
    from pathlib import Path

    from enshctl.download.types import DownloadConfig


class HostIO(Protocol):
    """Host operations used by the Install flow."""

    space: SpaceGuard

    def is_file(self, path: Path) -> bool: ...

    def is_symlink(self, path: Path) -> bool: ...

    def mkdir(self, path: Path) -> None: ...

    def touch(self, path: Path) -> None: ...

    def chown(self, *paths: Path, uid: int, gid: int) -> None: ...

    def make_readonly(self, path: Path) -> None: ...


@dataclass(frozen=True)
class SystemHostIO:
    """Production host adapter — filesystem ownership and subprocesses."""

    space: SpaceGuard = field(default_factory=SpaceGuard)

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_symlink(self, path: Path) -> bool:
        return path.is_symlink()

    def mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def touch(self, path: Path) -> None:
        path.touch()

    def chown(self, *paths: Path, uid: int, gid: int) -> None:
        files.chown_tree(*paths, uid=uid, gid=gid)

    def make_readonly(self, path: Path) -> None:
        subprocess.run(["chmod", "-R", "a-w", str(path)], check=False)


class DownloadIO(Protocol):
    """DepotDownloader and ManifestHub operations used by the Install flow."""

    def supports_manifestfile(self) -> bool: ...

    def ensure_depot_keys(self, manifests_dir: Path, repo_url: str | None) -> None: ...

    def download_manifest(
        self, depot_id: str, manifest_id: str, output_dir: Path, api_key: str, api_url: str
    ) -> Path: ...

    def list_manifest_ids(self) -> list[str]: ...

    def fetch_missing_manifests(
        self, manifest_ids: list[str], manifests_dir: Path, api_key: str, api_url: str
    ) -> None: ...

    def discover_depots(self) -> list[tuple[str, str]]: ...

    def download_depots(
        self,
        manifest_id: str,
        target_dir: Path,
        config: DownloadConfig,
        depot_manifests: list[tuple[str, str]] | None,
    ) -> None: ...


@dataclass(frozen=True)
class SystemDownloadIO:
    """Production download adapter — delegates to the DepotDownloader and ManifestHub adapters."""

    downloader: DepotDownloader = field(default_factory=DepotDownloader)

    def supports_manifestfile(self) -> bool:
        return self.downloader.supports_manifestfile()

    def ensure_depot_keys(self, manifests_dir: Path, repo_url: str | None) -> None:
        keys.ensure_depot_keys(manifests_dir, repo_url)

    def download_manifest(self, depot_id: str, manifest_id: str, output_dir: Path, api_key: str, api_url: str) -> Path:
        return hub.download_manifest_from_hub(depot_id, manifest_id, output_dir, api_key, api_url)

    def list_manifest_ids(self) -> list[str]:
        return self.downloader.list_manifest_ids()

    def fetch_missing_manifests(self, manifest_ids: list[str], manifests_dir: Path, api_key: str, api_url: str) -> None:
        hub.fetch_missing_manifests(manifest_ids, manifests_dir, api_key, api_url)

    def discover_depots(self) -> list[tuple[str, str]]:
        return self.downloader.discover_depots()

    def download_depots(
        self,
        manifest_id: str,
        target_dir: Path,
        config: DownloadConfig,
        depot_manifests: list[tuple[str, str]] | None,
    ) -> None:
        self.downloader.download_depots(manifest_id, target_dir, config, depot_manifests)
