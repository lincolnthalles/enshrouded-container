"""Tests for the shared free-space guard."""

from pathlib import Path
from unittest.mock import patch

import pytest
from enshctl.disk_space import SpaceGuard, SpaceVerdict
from enshctl.files import chown_tree, disk_free_bytes, read_tree_size


def test_verdict_available_and_shortfall() -> None:
    # GIVEN free plus existing bytes below the requirement
    verdict = SpaceVerdict(free_bytes=100, existing_bytes=20, required_bytes=150)
    # WHEN reading the verdict
    # THEN the available and shortfall sizes are exact
    assert verdict.available_bytes == 120
    assert verdict.shortfall_bytes == 30
    assert verdict.is_sufficient is False


def test_verdict_sufficient_when_available_meets_requirement() -> None:
    # GIVEN free plus existing bytes at the requirement
    verdict = SpaceVerdict(free_bytes=100, existing_bytes=20, required_bytes=120)
    # WHEN reading the verdict
    # THEN it is sufficient with no shortfall
    assert verdict.shortfall_bytes == 0
    assert verdict.is_sufficient is True


def test_guard_uses_injected_probes() -> None:
    # GIVEN a guard with deterministic probes
    guard = SpaceGuard(disk_free=lambda _path: 100, tree_size=lambda _path: 20)
    # WHEN checking a required size with existing bytes
    verdict = guard.check(Path("/data/backups"), required_bytes=150, existing_bytes=30)
    # THEN the probes supply the verdict
    assert verdict == SpaceVerdict(free_bytes=100, existing_bytes=30, required_bytes=150)
    assert guard.tree_size(Path("/data/saves")) == 20


def test_disk_free_bytes_uses_nearest_existing_parent(tmp_path: Path) -> None:
    # GIVEN a path whose intermediate directories do not exist
    missing = tmp_path / "missing" / "saves"
    with patch("enshctl.files.shutil.disk_usage") as mock_disk_usage:
        mock_disk_usage.return_value.free = 123
        # WHEN measuring free space
        result = disk_free_bytes(missing)
    # THEN the nearest existing ancestor is measured
    assert result == 123
    mock_disk_usage.assert_called_once_with(tmp_path)


def test_read_tree_size_excludes_symlinks(tmp_path: Path) -> None:
    # GIVEN a real file and a symlink to it
    (tmp_path / "save.db").write_bytes(b"data")
    (tmp_path / "save-link.db").symlink_to(tmp_path / "save.db")
    # WHEN measuring the tree
    # THEN only the real file counts
    assert read_tree_size(tmp_path) == 4


def test_read_tree_size_rejects_symlinked_root(tmp_path: Path) -> None:
    # GIVEN a symlink to a directory containing data
    target = tmp_path / "target"
    target.mkdir()
    (target / "save.db").write_bytes(b"data")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    # WHEN measuring the symlinked root
    # THEN it contributes no size
    assert read_tree_size(link) == 0


def test_chown_tree_applies_ownership_recursively(tmp_path: Path) -> None:
    # GIVEN a tree with a nested file and a symlink pointing outside it
    root = tmp_path / "tree"
    root.mkdir()
    (root / "top").write_bytes(b"")
    nested = root / "nested"
    nested.mkdir()
    (nested / "deep").write_bytes(b"")
    outside = tmp_path / "outside"
    outside.write_bytes(b"")
    (root / "link").symlink_to(outside)
    calls: list[tuple[Path, int, int, bool]] = []

    def _chown(path: Path, uid: int, gid: int, *, follow_symlinks: bool = True) -> None:
        calls.append((path, uid, gid, follow_symlinks))

    # WHEN applying ownership to the tree
    with patch("enshctl.files.chown", _chown):
        chown_tree(root, uid=1, gid=2)

    # THEN every entry is chowned and symlinks are not followed
    assert {path for path, *_ in calls} == {root, root / "top", nested, nested / "deep", root / "link"}
    assert all(follow is False for *_, follow in calls)


def test_chown_tree_lchowns_symlinked_root_without_following(tmp_path: Path) -> None:
    # GIVEN a symlink whose target is a directory outside the tree
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep").write_bytes(b"")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    calls: list[tuple[Path, bool]] = []

    def _chown(path: Path, uid: int, gid: int, *, follow_symlinks: bool = True) -> None:
        calls.append((path, follow_symlinks))

    # WHEN applying ownership to the symlinked root
    with patch("enshctl.files.chown", _chown):
        chown_tree(link, uid=1, gid=2)

    # THEN only the link itself is chowned and its target is not walked
    assert calls == [(link, False)]
    assert (target / "keep").read_bytes() == b""


def test_chown_tree_continues_after_a_failed_entry(tmp_path: Path) -> None:
    # GIVEN a tree whose first entry cannot be chowned
    root = tmp_path / "tree"
    root.mkdir()
    (root / "top").write_bytes(b"")
    nested = root / "nested"
    nested.mkdir()
    (nested / "deep").write_bytes(b"")
    calls: list[Path] = []

    def _chown(path: Path, uid: int, gid: int, *, follow_symlinks: bool = True) -> None:
        calls.append(path)
        if path == root / "top":
            msg = "nope"
            raise PermissionError(msg)

    # WHEN applying ownership
    with patch("enshctl.files.chown", _chown), pytest.raises(PermissionError):
        chown_tree(root, uid=1, gid=2)

    # THEN later entries are still attempted before the first error is raised
    assert nested / "deep" in calls
