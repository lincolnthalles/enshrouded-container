"""Per-manifest staging — Install, Game tree, Generated config, and Save directory readiness."""

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from enshctl import config, manifests, mods
from enshctl.download import flow as download_flow
from enshctl.download.types import InstallError, ManifestRecord
from enshctl.paths import SAVE_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from enshctl.config import SaveDirectories
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

STARTUP_ERRORS = (InstallError, OSError, subprocess.SubprocessError, ValueError, mods.GameTreeError)


@dataclass(frozen=True)
class PreparedServer:
    """Active Manifest and resolved Save directories after one staging pass."""

    active_manifest: ManifestRecord
    save_directories: SaveDirectories


class StagingIO(Protocol):
    """Operations needed by one staging pass."""

    def install_version(self, settings: AppSettings) -> Path: ...

    def install_manifest(self, manifest_id: str, settings: AppSettings) -> Path: ...

    def build_game_tree(self, manifest_id: str, settings: AppSettings) -> None: ...

    def write_config(self, settings: AppSettings) -> SaveDirectories: ...

    def cached_latest_manifest(self) -> ManifestRecord | None: ...

    def apply_ownership(self, save_directories: SaveDirectories, settings: AppSettings) -> None: ...


class ChownCallable(Protocol):
    """Callable that changes ownership without following symlinks."""

    def __call__(self, path: Path, uid: int, gid: int, *, follow_symlinks: bool) -> None: ...


@dataclass(frozen=True)
class SystemStagingIO:
    """Production adapter over the Install flow, Game tree, config, and ownership."""

    chown: ChownCallable = os.chown

    def install_version(self, settings: AppSettings) -> Path:
        download_flow.prepare_manifests(settings)
        manifest_id = manifests.resolve_manifest(settings.version)
        return download_flow.download_version(manifest_id, settings, version_spec=settings.version)

    def install_manifest(self, manifest_id: str, settings: AppSettings) -> Path:
        return download_flow.download_version(manifest_id, settings, version_spec=settings.version)

    def build_game_tree(self, manifest_id: str, settings: AppSettings) -> None:
        plan = mods.GameTreePlan.from_settings(manifest_id, settings)
        mods.build_game_tree(plan)

    def write_config(self, settings: AppSettings) -> SaveDirectories:
        return config.write_generated_config(settings)

    def cached_latest_manifest(self) -> ManifestRecord | None:
        return manifests.cached_latest_manifest()

    def apply_ownership(self, save_directories: SaveDirectories, settings: AppSettings) -> None:
        saves_dir = save_directories.saves_dir
        if saves_dir == SAVE_DIR:
            return
        saves_dir.mkdir(parents=True, exist_ok=True)
        ownership_failed = False
        for path in (saves_dir, *saves_dir.rglob("*")):
            try:
                self.chown(path, settings.puid, settings.pgid, follow_symlinks=False)
            except OSError as exc:
                if not ownership_failed:
                    logger.warning("Could not set ownership on %s: %s", path, exc)
                    ownership_failed = True


def ensure_installed(settings: AppSettings, *, staging_io: StagingIO | None = None) -> Path:
    """Ensure the Version spec's Manifest install exists."""
    adapter: StagingIO = staging_io or SystemStagingIO()
    return adapter.install_version(settings)


def stage(
    settings: AppSettings,
    *,
    target: ManifestRecord | None = None,
    staging_io: StagingIO | None = None,
) -> PreparedServer:
    """Prepare the Game tree and Generated config for one Manifest."""
    adapter: StagingIO = staging_io or SystemStagingIO()
    installed = (
        adapter.install_manifest(target.manifest_id, settings)
        if target is not None
        else adapter.install_version(settings)
    )
    adapter.build_game_tree(installed.name, settings)
    save_directories = adapter.write_config(settings)
    adapter.apply_ownership(save_directories, settings)
    cached = adapter.cached_latest_manifest()
    return PreparedServer(
        active_manifest=_active_manifest(installed.name, target=target, cached=cached),
        save_directories=save_directories,
    )


def _active_manifest(
    installed_id: str,
    *,
    target: ManifestRecord | None,
    cached: ManifestRecord | None,
) -> ManifestRecord:
    if cached is not None and cached.manifest_id == installed_id:
        return cached
    if target is not None and target.manifest_id == installed_id:
        return target
    return ManifestRecord(manifest_id=installed_id, timestamp="")
