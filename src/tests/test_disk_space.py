"""Tests for the shared free-space guard."""

from pathlib import Path
from unittest.mock import patch

from enshctl.disk_space import SpaceGuard, SpaceVerdict
from enshctl.files import disk_free_bytes, read_tree_size


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
