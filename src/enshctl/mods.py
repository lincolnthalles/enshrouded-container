"""Symlink-tree mod injection layer."""

import logging
import shutil
from dataclasses import dataclass
from os import chown
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from enshctl.paths import (
    BACKUP_BASE_DIR,
    CONFIG_DIR,
    CONFIG_FILENAME,
    GAME_TREE_DIR,
    LOG_DIR,
    MANIFESTS_DIR,
    MOD_OVERLAY_DIR,
    SAVE_DIR,
    WINE_PREFIX,
)

if TYPE_CHECKING:
    from enshctl.settings import AppSettings

DEFAULT_DLL_OVERRIDES = "mscoree,mshtml="

logger = logging.getLogger(__name__)


class GameTreeError(Exception):
    """The Game tree plan cannot be built safely."""


@dataclass(frozen=True)
class GameTreePlan:
    manifest_id: str
    persist_files: tuple[str, ...]
    puid: int
    pgid: int
    manifests_dir: Path = MANIFESTS_DIR
    game_tree_dir: Path = GAME_TREE_DIR
    mod_overlay_dir: Path = MOD_OVERLAY_DIR
    config_dir: Path = CONFIG_DIR
    backup_dir: Path = BACKUP_BASE_DIR

    def __post_init__(self) -> None:
        """Reject roots that the destructive rebuild would delete."""
        protected = (
            self.manifests_dir,
            self.mod_overlay_dir,
            self.config_dir,
            self.backup_dir,
            SAVE_DIR,
            LOG_DIR,
            BACKUP_BASE_DIR,
            WINE_PREFIX,
        )
        if self.manifest_id:
            protected = (self.manifests_dir / self.manifest_id, *protected)
        try:
            target = self.game_tree_dir.resolve(strict=False)
            resolved = [path.resolve(strict=False) for path in protected]
        except OSError, RuntimeError, ValueError:
            target = self.game_tree_dir
            resolved = list(protected)
        for path, resolved_path in zip(protected, resolved, strict=True):
            if target == resolved_path or target.is_relative_to(resolved_path) or resolved_path.is_relative_to(target):
                msg = f"Game tree directory {self.game_tree_dir} overlaps protected root {path}"
                raise GameTreeError(msg)

    @classmethod
    def from_settings(cls, manifest_id: str, settings: AppSettings) -> GameTreePlan:
        return cls(
            manifest_id=manifest_id,
            persist_files=settings.persist_files,
            puid=settings.puid,
            pgid=settings.pgid,
            backup_dir=Path(settings.backup_dir),
        )


def generate_dll_overrides(mod_overlay_dir: Path = MOD_OVERLAY_DIR) -> str:
    """Scan the Mod overlay for DLLs and generate WINEDLLOVERRIDES string.

    DLLs with a ``win*`` prefix (case-insensitive) get ``n,b`` override.
    All other DLLs get ``n`` override. The baseline ``mscoree,mshtml=``
    is always prepended.
    """
    overrides: list[str] = []
    if mod_overlay_dir.exists():
        for dll_path in mod_overlay_dir.rglob("*"):
            if dll_path.is_file() and dll_path.suffix.lower() == ".dll":
                stem = dll_path.stem.lower()
                override_type = "n,b" if stem.startswith("win") else "n"
                overrides.append(f"{stem}={override_type}")

    parts = [DEFAULT_DLL_OVERRIDES]
    if overrides:
        parts.extend(sorted(overrides))
    return ",".join(parts)


def resolve_dll_overrides(settings: AppSettings) -> str:
    """Choose explicit WINEDLLOVERRIDES or generate them from the Mod overlay."""
    if settings.winedlloverrides is not None:
        logger.info("Using user-provided WINEDLLOVERRIDES: %s", settings.winedlloverrides)
        return settings.winedlloverrides
    generated = generate_dll_overrides()
    logger.info("Generated WINEDLLOVERRIDES: %s", generated)
    return generated


def _overlay_mods(mod_overlay_dir: Path, target: Path) -> None:
    """Overlay mod files by creating symlinks, overriding manifest symlinks."""
    for mod_file in mod_overlay_dir.rglob("*"):
        if not mod_file.is_file():
            continue
        rel = mod_file.relative_to(mod_overlay_dir)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        dest.symlink_to(mod_file)


def _setup_persist_files(
    manifest: Path,
    target: Path,
    persist_files: tuple[str, ...],
    config_dir: Path,
) -> None:
    """Handle PERSIST_FILES: copy persisted files to config dir and symlink them."""
    for filename in persist_files:
        if filename == CONFIG_FILENAME:
            continue  # Already handled separately

        # Reject path traversal attempts
        if "../" in filename or "..\\" in filename:
            logger.warning("Skipping invalid PERSIST_FILES entry (path traversal): %s", filename)
            continue

        # Reject absolute paths and dot segments anywhere (PurePath containment check)
        parts = PurePath(filename).parts
        if PurePath(filename).is_absolute() or not parts or ".." in parts or "." in parts:
            logger.warning("Skipping invalid PERSIST_FILES entry (not a relative file path): %s", filename)
            continue

        source = manifest / filename
        dest = target / filename
        persist_path = config_dir / filename

        if not source.exists() and not dest.exists():
            continue

        # Seed persisted file from manifest if not present
        # Use shutil.copy (not copy2) to avoid inheriting read-only mode from manifest
        if not persist_path.exists() and source.exists():
            shutil.copy(source, persist_path)

        # Replace with symlink
        dest.unlink(missing_ok=True)
        dest.symlink_to(persist_path)


def build_game_tree(plan: GameTreePlan) -> None:
    """Build the Game tree as a symlink tree from the Manifest install plus the Mod overlay.

    On every startup:
    1. Wipe the Game tree directory
    2. Symlink Manifest install files
    3. Overlay mod files (force-create symlinks)
    4. Config symlink to the config directory
    5. Handle PERSIST_FILES for additional writable files
    """
    manifest = plan.manifests_dir / plan.manifest_id
    target = plan.game_tree_dir

    if not manifest.exists():
        logger.error("Manifest install does not exist: %s", manifest)
        msg = f"Manifest install not found: {manifest}"
        raise FileNotFoundError(msg)

    if not plan.mod_overlay_dir.exists():
        logger.info("Creating Mod overlay directory: %s", plan.mod_overlay_dir)
        plan.mod_overlay_dir.mkdir(parents=True, exist_ok=True)

    # Wipe target
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            logger.warning("Failed to fully remove %s, attempting rebuild anyway", target)
    target.mkdir(parents=True, exist_ok=True)

    # Symlink manifest files (pure Python, no cp -as — avoids EPERM in CI)
    for src in manifest.rglob("*"):
        if not src.is_file():
            continue
        dest = target / src.relative_to(manifest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src)

    # Overlay mod files
    if plan.mod_overlay_dir.exists():
        mod_files = sorted(f.relative_to(plan.mod_overlay_dir) for f in plan.mod_overlay_dir.rglob("*") if f.is_file())
        if mod_files:
            logger.info("Overlaying %d mod file(s): %s", len(mod_files), ", ".join(str(m) for m in mod_files))
        else:
            logger.info("No mod files found in %s", plan.mod_overlay_dir)
        _overlay_mods(plan.mod_overlay_dir, target)

    # Config symlink
    plan.config_dir.mkdir(parents=True, exist_ok=True)
    game_config = target / CONFIG_FILENAME
    game_config.unlink(missing_ok=True)
    game_config.symlink_to(plan.config_dir / CONFIG_FILENAME)

    # PERSIST_FILES
    _setup_persist_files(manifest, target, plan.persist_files, plan.config_dir)

    # Set ownership (may fail in unprivileged environments like CI)
    try:
        chown(target, plan.puid, plan.pgid)
    except OSError:
        logger.debug("Could not chown %s to %d:%d (unprivileged environment?)", target, plan.puid, plan.pgid)

    logger.info("Game tree built at %s", target)
