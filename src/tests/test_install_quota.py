"""Tests for install disk space quota checks."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from enshctl.install import DEFAULT_MIN_FREE_SPACE, get_min_free_space


def test_get_min_free_space_default() -> None:
    if "INSTALL_MIN_FREE_SPACE" in os.environ:
        del os.environ["INSTALL_MIN_FREE_SPACE"]
    assert get_min_free_space() == DEFAULT_MIN_FREE_SPACE


def test_get_min_free_space_custom() -> None:
    os.environ["INSTALL_MIN_FREE_SPACE"] = str(5 * 1024**3)
    try:
        assert get_min_free_space() == 5 * 1024**3
    finally:
        del os.environ["INSTALL_MIN_FREE_SPACE"]


def test_get_min_free_space_invalid_fallback() -> None:
    os.environ["INSTALL_MIN_FREE_SPACE"] = "not-a-number"
    try:
        assert get_min_free_space() == DEFAULT_MIN_FREE_SPACE
    finally:
        del os.environ["INSTALL_MIN_FREE_SPACE"]


class TestDownloadVersionQuota:
    """Tests for download_version() disk space checks."""

    def test_install_quota_sufficient_space(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        mock_disk = MagicMock()
        mock_disk.free = 12 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", manifests_dir),
            patch.object(install, "get_version", return_value="999"),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch("os.chown"),
            patch.object(install, "_ensure_manifest_for_version", return_value=Path("/nonexistent")),
            patch.object(install, "check_manifestfile_support", return_value=False),
            patch.object(install, "download_depots"),
            patch.object(install, "sys"),
        ):
            install.download_version("999", force=True)

        assert True

    def test_install_quota_insufficient_space_aborts(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        mock_disk = MagicMock()
        mock_disk.free = 8 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "get_version", return_value="999"),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch.object(install, "_ensure_manifest_for_version", return_value=Path("/nonexistent")),
            patch.object(install, "check_manifestfile_support", return_value=False),
            patch.object(install, "download_depots"),
            patch.object(install, "sys") as mock_sys,
        ):
            install.download_version("999", force=True)
            mock_sys.exit.assert_called_once_with(1)

    def test_install_quota_same_manifest_partial_counts(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "partial_chunk.dat").write_bytes(b"data")
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        mock_disk = MagicMock()
        mock_disk.free = 9 * 1024**3  # below 10 GB, but partial adds ~4 bytes

        with (
            patch.object(install, "MANIFESTS_DIR", manifests_dir),
            patch.object(install, "get_version", return_value="999"),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch.object(install, "get_min_free_space", return_value=9 * 1024**3 + 1),
            patch("os.chown"),
            patch.object(install, "_ensure_manifest_for_version", return_value=Path("/nonexistent")),
            patch.object(install, "check_manifestfile_support", return_value=False),
            patch.object(install, "download_depots"),
            patch.object(install, "sys"),
        ):
            install.download_version("999", force=True)

        assert True

    def test_install_quota_different_manifest_partial_ignored(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        partial_dir = manifests_dir / "888"
        partial_dir.mkdir()
        (partial_dir / "partial_chunk.dat").write_bytes(b"data")

        mock_disk = MagicMock()
        mock_disk.free = 7 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", manifests_dir),
            patch.object(install, "get_version", return_value="999"),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch.object(install, "sys") as mock_sys,
        ):
            install.download_version("999", force=True)
            mock_sys.exit.assert_called_once_with(1)
