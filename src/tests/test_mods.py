"""Tests for symlink-tree mod injection layer."""

import contextlib
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from enshctl.mods import (
    CONFIG_FILENAME,
    GameTreePlan,
    build_game_tree,
)
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_MOD = "enshctl.mods"


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


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


def _tree_context(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest = _setup_manifest(tmp_path)
    target = tmp_path / "gameserver"
    config = tmp_path / "config"
    config.mkdir()
    return manifest, target, config


@contextlib.contextmanager
def _patched_tree(manifest: Path, target: Path, config: Path, mods: Path) -> Iterator[None]:
    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", manifest),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", mods),
        mock.patch(f"{_MOD}.CONFIG_DIR", config),
    ):
        yield


# --- build_game_tree tests ---


def test_build_game_tree_creates_symlink_tree(tmp_path: Path) -> None:
    # GIVEN a manifest with files
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", (), 1000, 1000))

    # THEN manifest files are symlinked into the target
    assert (target / "enshrouded_server.exe").read_text() == "exe-content"
    assert (target / "data" / "game.dat").read_bytes() == b"\x00\x01\x02"
    assert (target / "enshrouded_server_example.json").read_text() == "{}"


def test_build_game_tree_wipes_existing_directory(tmp_path: Path) -> None:
    # GIVEN a target with stale contents
    manifest, target, config = _tree_context(tmp_path)
    target.mkdir()
    (target / "old_file.txt").write_text("stale")

    # WHEN rebuilding the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan(version="test-version", persist_files=(), puid=1000, pgid=1000))

    # THEN stale contents are removed and manifest files present
    assert not (target / "old_file.txt").exists()
    assert (target / "enshrouded_server.exe").exists()


def test_build_game_tree_overlay_mods(tmp_path: Path) -> None:
    # GIVEN a manifest and a mod DLL
    manifest, target, config = _tree_context(tmp_path)
    mods = _setup_mods(tmp_path)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, mods):
        build_game_tree(GameTreePlan("test-version", (), 1000, 1000))

    # THEN the mod file is present alongside manifest files
    assert (target / "plugins" / "my_mod.dll").is_symlink()
    assert (target / "plugins" / "my_mod.dll").read_bytes() == b"\x00"
    assert (target / "enshrouded_server.exe").exists()


def test_build_game_tree_config_symlink(tmp_path: Path) -> None:
    # GIVEN a manifest
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", (), 1000, 1000))

    # THEN the game config symlinks to the config dir
    game_config = target / CONFIG_FILENAME
    assert game_config.is_symlink()
    assert game_config.resolve() == config.resolve() / CONFIG_FILENAME


def test_build_game_tree_manifest_not_found(tmp_path: Path) -> None:
    # GIVEN no manifest directory
    target = tmp_path / "gameserver"

    # WHEN building a missing version
    # THEN FileNotFoundError propagates
    with (
        mock.patch(f"{_MOD}.MANIFESTS_DIR", tmp_path / "nonexistent"),
        mock.patch(f"{_MOD}.MOUNT_POINT", target),
        mock.patch(f"{_MOD}.MODS_DIR", tmp_path / "nonexistent"),
        pytest.raises(FileNotFoundError),
    ):
        build_game_tree(GameTreePlan("nonexistent-version", (), 1000, 1000))


def test_build_game_tree_persist_files(tmp_path: Path) -> None:
    # GIVEN a manifest file listed in persist_files
    manifest, target, config = _tree_context(tmp_path)
    (manifest / "test-version" / "extra.dat").write_bytes(b"\x03\x04")

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", ("extra.dat",), 1000, 1000))

    # THEN the file is copied to the config dir and symlinked from the target
    assert (config / "extra.dat").exists()
    assert (config / "extra.dat").read_bytes() == b"\x03\x04"
    assert (target / "extra.dat").is_symlink()
    assert (target / "extra.dat").resolve() == (config / "extra.dat").resolve()


def test_build_game_tree_persist_files_skips_path_traversal(tmp_path: Path) -> None:
    # GIVEN a persist entry attempting path traversal
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", ("../../etc/passwd",), 1000, 1000))

    # THEN the traversal is rejected
    assert not (tmp_path / "etc" / "passwd").exists()
    assert not (config / "passwd").exists()


def test_build_game_tree_persist_files_skips_missing(tmp_path: Path) -> None:
    # GIVEN a persist entry for a nonexistent file
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", ("nonexistent.dat",), 1000, 1000))

    # THEN no file is created
    assert not (config / "nonexistent.dat").exists()
    assert not (target / "nonexistent.dat").exists()


def test_build_game_tree_persist_files_copies_readonly_source(tmp_path: Path) -> None:
    # GIVEN a read-only manifest file listed in persist_files
    manifest, target, config = _tree_context(tmp_path)
    (manifest / "test-version" / "persist.dat").write_bytes(b"\x05\x06")
    (manifest / "test-version" / "persist.dat").chmod(0o444)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", ("persist.dat",), 1000, 1000))

    # THEN the persisted copy matches the source bytes
    persisted = config / "persist.dat"
    assert persisted.exists()
    assert persisted.read_bytes() == b"\x05\x06"
    assert not persisted.stat().st_mode & 0o200


def test_build_game_tree_persist_files_skips_config_filename(tmp_path: Path) -> None:
    # GIVEN the game config filename listed in persist_files
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    with _patched_tree(manifest, target, config, tmp_path / "nonexistent"):
        build_game_tree(GameTreePlan("test-version", (CONFIG_FILENAME,), 1000, 1000))

    # THEN persist handling leaves the config symlink alone and creates nothing
    assert (target / CONFIG_FILENAME).is_symlink()
    assert not (config / CONFIG_FILENAME).exists()
