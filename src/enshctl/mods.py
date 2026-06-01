"""Symlink-tree mod injection layer."""

import logging
import shutil
import subprocess
from os import chown, environ
from typing import TYPE_CHECKING

from enshctl.settings import CONFIG_DIR, CONFIG_FILENAME, MANIFESTS_DIR, MODS_DIR, MOUNT_POINT

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_DLL_OVERRIDES = "mscoree,mshtml="

logger = logging.getLogger(__name__)


def generate_dll_overrides(mods_dir: Path = MODS_DIR) -> str:
    """Scan mods directory for DLLs and generate WINEDLLOVERRIDES string.

    DLLs with a ``win*`` prefix (case-insensitive) get ``n,b`` override.
    All other DLLs get ``n`` override. The baseline ``mscoree,mshtml=``
    is always prepended.
    """
    overrides: list[str] = []
    if mods_dir.exists():
        for dll_path in mods_dir.rglob("*"):
            if dll_path.is_file() and dll_path.suffix.lower() == ".dll":
                stem = dll_path.stem.lower()
                override_type = "n,b" if stem.startswith("win") else "n"
                overrides.append(f"{stem}={override_type}")

    parts = [DEFAULT_DLL_OVERRIDES]
    if overrides:
        parts.extend(sorted(overrides))
    return ",".join(parts)


def _overlay_mods(mods_dir: Path, target: Path) -> None:
    """Overlay mod files by creating symlinks, overriding manifest symlinks."""
    for mod_file in mods_dir.rglob("*"):
        if not mod_file.is_file():
            continue
        rel = mod_file.relative_to(mods_dir)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        dest.symlink_to(mod_file)


def _setup_persist_files(manifest: Path, target: Path) -> None:
    """Handle PERSIST_FILES: copy persisted files to config dir and symlink them."""
    raw = environ.get("PERSIST_FILES", "")
    persist_files = [f.strip() for f in raw.split(",") if f.strip()]

    for filename in persist_files:
        if filename == CONFIG_FILENAME:
            continue  # Already handled separately

        # Reject path traversal attempts
        if "../" in filename or "..\\" in filename:
            logger.warning("Skipping invalid PERSIST_FILES entry (path traversal): %s", filename)
            continue

        source = manifest / filename
        dest = target / filename
        persist_path = CONFIG_DIR / filename

        if not source.exists() and not dest.exists():
            continue

        # Seed persisted file from manifest if not present
        # Use shutil.copy (not copy2) to avoid inheriting read-only mode from manifest
        if not persist_path.exists() and source.exists():
            shutil.copy(source, persist_path)

        # Replace with symlink
        dest.unlink(missing_ok=True)
        dest.symlink_to(persist_path)


def build_game_tree(version: str, *, puid: int = 1000, pgid: int = 1000) -> None:
    """Build /data/gameserver/ as a symlink tree from manifest + mods.

    On every startup:
    1. Wipe /data/gameserver/
    2. Symlink manifest files (cp -as)
    3. Overlay mod files (force-create symlinks)
    4. Config symlink to /data/config/enshrouded_server.json
    5. Handle PERSIST_FILES for additional writable files
    """
    manifest = MANIFESTS_DIR / version
    target = MOUNT_POINT

    if not manifest.exists():
        logger.error("Game version directory does not exist: %s", manifest)
        msg = f"Game version directory not found: {manifest}"
        raise FileNotFoundError(msg)

    if not MODS_DIR.exists():
        logger.info("Creating mods directory: %s", MODS_DIR)
        MODS_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe target
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            logger.warning("Failed to fully remove %s, attempting rebuild anyway", target)
    target.mkdir(parents=True, exist_ok=True)

    # Symlink manifest files
    subprocess.run(["cp", "-as", f"{manifest}/.", str(target)], check=True)

    # Overlay mod files
    if MODS_DIR.exists():
        mod_files = sorted(f.relative_to(MODS_DIR) for f in MODS_DIR.rglob("*") if f.is_file())
        if mod_files:
            logger.info("Overlaying %d mod file(s): %s", len(mod_files), ", ".join(str(m) for m in mod_files))
        else:
            logger.info("No mod files found in %s", MODS_DIR)
        _overlay_mods(MODS_DIR, target)

    # Config symlink
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    game_config = target / CONFIG_FILENAME
    game_config.unlink(missing_ok=True)
    game_config.symlink_to(CONFIG_DIR / CONFIG_FILENAME)

    # PERSIST_FILES
    _setup_persist_files(manifest, target)

    # Set ownership
    chown(target, puid, pgid)

    logger.info("Game tree built at %s", target)
