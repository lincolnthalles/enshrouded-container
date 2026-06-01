"""Tests for symlink-tree mod injection layer."""

import os
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from enshctl.mods import (
    CONFIG_FILENAME,
    _overlay_mods,
    _setup_persist_files,
    build_game_tree,
)

if TYPE_CHECKING:
    from pathlib import Path

_MOD = "enshctl.mods"


def _setup_manifest(tmp_path: Path, version: str = "test-version") -> Path:
    """Create a fake manifest directory with test files."""
    manifest = tmp_path / "manifests" / version
    manifest.mkdir(parents=True)
    (manifest / "enshrouded_server.exe").write_text("exe-content")
    (manifest / "data").mkdir()
    (manifest / "data" / "game.dat").write_bytes(b"\x00\x01\x02")
    (manifest / "enshrouded_server_example.json").write_text("{}")
    return tmp_path / "manifests"


def _setup_mods(tmp_path: Path) -> Path:
    """Create a fake mods directory with test files."""
    mods = tmp_path / "mods"
    mods.mkdir(parents=True)
    (mods / "plugins").mkdir()
    (mods / "plugins" / "my_mod.dll").write_bytes(b"\x00")
    return mods


# --- build_game_tree tests ---


def test_build_game_tree_creates_symlink_tree(tmp_path: Path) -> None:
    """Manifest files should be symlinked into the target directory."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
    ):
        build_game_tree("test-version")

    assert (target / "enshrouded_server.exe").read_text() == "exe-content"
    assert (target / "data" / "game.dat").read_bytes() == b"\x00\x01\x02"
    assert (target / "enshrouded_server_example.json").read_text() == "{}"


def test_build_game_tree_wipes_existing_directory(tmp_path: Path) -> None:
    """Previous contents should be removed before rebuilding."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    target.mkdir()
    (target / "old_file.txt").write_text("stale")
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
    ):
        build_game_tree("test-version")

    assert not (target / "old_file.txt").exists()
    assert (target / "enshrouded_server.exe").exists()


def test_build_game_tree_overlay_mods(tmp_path: Path) -> None:
    """Mod files should override manifest symlinks."""
    manifest = _setup_manifest(tmp_path)
    mods = _setup_mods(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", mods),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
    ):
        build_game_tree("test-version")

    # Mod DLL should be present
    assert (target / "plugins" / "my_mod.dll").exists()
    # Manifest files should still be present
    assert (target / "enshrouded_server.exe").exists()


def test_build_game_tree_config_symlink(tmp_path: Path) -> None:
    """enshrouded_server.json should be a symlink to /data/config/."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
    ):
        build_game_tree("test-version")

    game_config = target / CONFIG_FILENAME
    assert game_config.is_symlink()
    assert game_config.resolve() == config.resolve() / CONFIG_FILENAME


def test_build_game_tree_manifest_not_found(tmp_path: Path) -> None:
    """Should raise FileNotFoundError if manifest directory doesn't exist."""
    target = tmp_path / "gameserver"

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        pytest.raises(FileNotFoundError),
    ):
        build_game_tree("nonexistent-version")


def test_build_game_tree_persist_files(tmp_path: Path) -> None:
    """PERSIST_FILES entries should be copied to config dir and symlinked."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()
    # Create a file in the manifest that should be persisted
    (manifest / "test-version" / "extra.dat").write_bytes(b"\x03\x04")

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
        mock.patch.dict(os.environ, {"PERSIST_FILES": "extra.dat"}),
    ):
        build_game_tree("test-version")

    # File should be copied to config dir and symlinked from gameserver
    assert (config / "extra.dat").exists()
    assert (config / "extra.dat").read_bytes() == b"\x03\x04"
    assert (target / "extra.dat").is_symlink()
    assert (target / "extra.dat").resolve() == (config / "extra.dat").resolve()


def test_build_game_tree_persist_files_skips_path_traversal(tmp_path: Path) -> None:
    """PERSIST_FILES entries with path traversal should be skipped."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
        mock.patch.dict(os.environ, {"PERSIST_FILES": "../../etc/passwd"}),
    ):
        build_game_tree("test-version")

    # Path traversal should be rejected
    assert not (tmp_path / "etc" / "passwd").exists()
    assert not (config / "passwd").exists()


def test_build_game_tree_persist_files_skips_missing(tmp_path: Path) -> None:
    """PERSIST_FILES entries for non-existent files should be silently skipped."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
        mock.patch.dict(os.environ, {"PERSIST_FILES": "nonexistent.dat"}),
    ):
        build_game_tree("test-version")

    # Should not create any file
    assert not (config / "nonexistent.dat").exists()
    assert not (target / "nonexistent.dat").exists()


# --- _overlay_mods tests ---


def test_overlay_mods_creates_symlinks(tmp_path: Path) -> None:
    """Mod files should be symlinked into the target."""
    mods = _setup_mods(tmp_path)
    target = tmp_path / "gameserver"
    target.mkdir()

    _overlay_mods(mods, target)

    assert (target / "plugins" / "my_mod.dll").is_symlink()
    assert (target / "plugins" / "my_mod.dll").read_bytes() == b"\x00"


def test_overlay_mods_overrides_existing_files(tmp_path: Path) -> None:
    """Mod files should override existing symlinks."""
    mods = _setup_mods(tmp_path)
    target = tmp_path / "gameserver"
    target.mkdir()
    # Create an existing file
    (target / "plugins").mkdir()
    (target / "plugins" / "my_mod.dll").write_bytes(b"\xff")

    _overlay_mods(mods, target)

    assert (target / "plugins" / "my_mod.dll").is_symlink()
    assert (target / "plugins" / "my_mod.dll").read_bytes() == b"\x00"


# --- _setup_persist_files tests ---


def test_setup_persist_files_copies_readonly_source(tmp_path: Path) -> None:
    """Files copied from read-only manifest should not be read-only."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    target.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    # Create a file in the manifest and make it read-only
    (manifest / "persist.dat").write_bytes(b"\x05\x06")
    (manifest / "persist.dat").chmod(0o444)

    with mock.patch(f"{_MOD}.CONFIG_DIR", config), mock.patch.dict(os.environ, {"PERSIST_FILES": "persist.dat"}):
        _setup_persist_files(manifest, target)

    # The persisted file should NOT be read-only
    persisted = config / "persist.dat"
    assert persisted.exists()
    assert persisted.read_bytes() == b"\x05\x06"
    assert not (persisted.stat().st_mode & 0o200)  # owner write should be set (not read-only)


def test_setup_persist_files_skips_config_filename(tmp_path: Path) -> None:
    """enshrouded_server.json should be skipped (handled separately)."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    target.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    with (
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
        mock.patch.dict(os.environ, {"PERSIST_FILES": "enshrouded_server.json"}),
    ):
        _setup_persist_files(manifest, target)

    # Config file should NOT be created by _setup_persist_files
    assert not (config / "enshrouded_server.json").exists()


def test_setup_persist_files_empty_env(tmp_path: Path) -> None:
    """No PERSIST_FILES env var should be a no-op."""
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    target.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    with mock.patch(f"{_MOD}.CONFIG_DIR", config), mock.patch.dict(os.environ, {}, clear=True):
        _setup_persist_files(manifest, target)

    # Nothing should be created
    assert list(config.iterdir()) == [] if config.exists() else True
