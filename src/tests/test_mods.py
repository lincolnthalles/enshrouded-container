"""Tests for the symlink-tree mod injection layer."""

from typing import TYPE_CHECKING

import pytest
from enshctl.mods import (
    CONFIG_FILENAME,
    GameTreeError,
    GameTreePlan,
    build_game_tree,
)
from enshctl.paths import GAME_TREE_DIR, SAVE_DIR
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path


def _setup_manifest(tmp_path: Path, manifest_id: str = "test-version") -> Path:
    """Create a fake manifest directory with test files."""
    manifest = tmp_path / "manifests" / manifest_id
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


def _build(
    manifest: Path,
    target: Path,
    config: Path,
    *,
    mods: Path | None = None,
    manifest_id: str = "test-version",
    persist_files: tuple[str, ...] = (),
) -> None:
    build_game_tree(
        GameTreePlan(
            manifest_id,
            persist_files,
            1000,
            1000,
            manifests_dir=manifest,
            game_tree_dir=target,
            mod_overlay_dir=mods if mods is not None else target.parent / "mods-absent",
            config_dir=config,
        )
    )


# --- build_game_tree tests ---


def test_build_game_tree_creates_symlink_tree(tmp_path: Path) -> None:
    # GIVEN a manifest with files
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config)

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
    _build(manifest, target, config)

    # THEN stale contents are removed and manifest files present
    assert not (target / "old_file.txt").exists()
    assert (target / "enshrouded_server.exe").exists()


def test_build_game_tree_overlay_mods(tmp_path: Path) -> None:
    # GIVEN a manifest and a mod DLL
    manifest, target, config = _tree_context(tmp_path)
    mods = _setup_mods(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config, mods=mods)

    # THEN the mod file is present alongside manifest files
    assert (target / "plugins" / "my_mod.dll").is_symlink()
    assert (target / "plugins" / "my_mod.dll").read_bytes() == b"\x00"
    assert (target / "enshrouded_server.exe").exists()


def test_build_game_tree_config_symlink(tmp_path: Path) -> None:
    # GIVEN a manifest
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config)

    # THEN the game config symlinks to the config dir
    game_config = target / CONFIG_FILENAME
    assert game_config.is_symlink()
    assert game_config.resolve() == config.resolve() / CONFIG_FILENAME


def test_build_game_tree_manifest_not_found(tmp_path: Path) -> None:
    # GIVEN no manifest directory
    target = tmp_path / "gameserver"

    # WHEN building a missing version
    # THEN FileNotFoundError propagates
    with pytest.raises(FileNotFoundError):
        _build(tmp_path / "manifests", target, tmp_path / "config", manifest_id="nonexistent-version")


def test_build_game_tree_persist_files(tmp_path: Path) -> None:
    # GIVEN a manifest file listed in persist_files
    manifest, target, config = _tree_context(tmp_path)
    (manifest / "test-version" / "extra.dat").write_bytes(b"\x03\x04")

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=("extra.dat",))

    # THEN the file is copied to the config dir and symlinked from the target
    assert (config / "extra.dat").exists()
    assert (config / "extra.dat").read_bytes() == b"\x03\x04"
    assert (target / "extra.dat").is_symlink()
    assert (target / "extra.dat").resolve() == (config / "extra.dat").resolve()


def test_build_game_tree_persist_files_skips_path_traversal(tmp_path: Path) -> None:
    # GIVEN a persist entry attempting path traversal
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=("../../etc/passwd",))

    # THEN the traversal is rejected
    assert not (tmp_path / "etc" / "passwd").exists()
    assert not (config / "passwd").exists()


def test_build_game_tree_persist_files_skips_absolute_path(tmp_path: Path) -> None:
    # GIVEN an absolute path pointing at an existing file
    manifest, target, config = _tree_context(tmp_path)
    outside = tmp_path / "outside.dat"
    outside.write_bytes(b"sensitive")

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=(str(outside),))

    # THEN the entry is rejected and the outside file is left untouched
    assert outside.read_bytes() == b"sensitive"
    assert not outside.is_symlink()
    assert list(config.iterdir()) == []


def test_build_game_tree_persist_files_skips_bare_dots(tmp_path: Path) -> None:
    # GIVEN persist entries that are bare dot segments
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=(".", ".."))

    # THEN the entries are rejected without touching the tree parents
    assert target.is_dir()


def test_build_game_tree_persist_files_skips_missing(tmp_path: Path) -> None:
    # GIVEN a persist entry for a nonexistent file
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=("nonexistent.dat",))

    # THEN no file is created
    assert not (config / "nonexistent.dat").exists()
    assert not (target / "nonexistent.dat").exists()


def test_build_game_tree_persist_files_copies_readonly_source(tmp_path: Path) -> None:
    # GIVEN a read-only manifest file listed in persist_files
    manifest, target, config = _tree_context(tmp_path)
    (manifest / "test-version" / "persist.dat").write_bytes(b"\x05\x06")
    (manifest / "test-version" / "persist.dat").chmod(0o444)

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=("persist.dat",))

    # THEN the persisted copy matches the source bytes
    persisted = config / "persist.dat"
    assert persisted.exists()
    assert persisted.read_bytes() == b"\x05\x06"
    assert not persisted.stat().st_mode & 0o200


def test_build_game_tree_persist_files_skips_config_filename(tmp_path: Path) -> None:
    # GIVEN the game config filename listed in persist_files
    manifest, target, config = _tree_context(tmp_path)

    # WHEN building the game tree
    _build(manifest, target, config, persist_files=(CONFIG_FILENAME,))

    # THEN persist handling leaves the config symlink alone and creates nothing
    assert (target / CONFIG_FILENAME).is_symlink()
    assert not (config / CONFIG_FILENAME).exists()


def test_game_tree_plan_accepts_production_roots() -> None:
    # GIVEN the default plan
    plan = GameTreePlan.from_settings("999", AppSettings())

    # THEN the plan is accepted and targets the production Game tree
    assert plan.game_tree_dir == GAME_TREE_DIR


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("equal_overlay", "/mods-overlay"),
        ("nested_overlay", "/mods-overlay"),
        ("symlink_overlay", "/mods-overlay"),
        ("contains_config", "/config"),
        ("backup", "/backups"),
        ("saves", str(SAVE_DIR)),
    ],
)
def test_game_tree_plan_rejects_overlapping_roots(tmp_path: Path, case: str, expected: str) -> None:
    # GIVEN a Game tree location that overlaps exactly one protected root
    overlay = tmp_path / "mods-overlay"
    backup = tmp_path / "backups"
    if case == "equal_overlay":
        game_tree = overlay
        config_dir = tmp_path / "config"
    elif case in {"nested_overlay", "symlink_overlay"}:
        game_tree = overlay / "tree"
        config_dir = tmp_path / "config"
    elif case == "contains_config":
        game_tree = tmp_path / "tree"
        config_dir = game_tree / "config"
    elif case == "backup":
        game_tree = backup
        config_dir = tmp_path / "config"
    else:
        game_tree = SAVE_DIR
        config_dir = tmp_path / "config"
    if case == "symlink_overlay":
        game_tree.parent.mkdir(parents=True, exist_ok=True)
        game_tree.symlink_to(overlay)

    # WHEN building a plan for those roots
    # THEN the plan is rejected with an error naming both paths
    with pytest.raises(GameTreeError) as exc_info:
        GameTreePlan(
            "test-version",
            (),
            1000,
            1000,
            manifests_dir=tmp_path / "manifests",
            game_tree_dir=game_tree,
            mod_overlay_dir=overlay,
            config_dir=config_dir,
            backup_dir=backup,
        )

    message = str(exc_info.value)
    assert "Game tree directory" in message
    assert str(game_tree) in message
    assert expected in message
