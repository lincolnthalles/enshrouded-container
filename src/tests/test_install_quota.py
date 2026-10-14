"""Tests for install disk space quota checks."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from enshctl.settings import AppSettings


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


class TestDownloadVersionQuota:
    """Tests for download_version() disk space checks."""

    def test_install_quota_sufficient_space(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        # GIVEN a partially installed manifest and ample free space
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        mock_disk = MagicMock()
        mock_disk.free = 12 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", manifests_dir),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch("os.chown"),
            patch.object(install, "_ensure_manifest_for_version", return_value=Path("/nonexistent")),
            patch.object(install, "check_manifestfile_support", return_value=False),
            patch.object(install, "download_depots"),
        ):
            # WHEN downloading with sufficient space
            install.download_version("999", _settings(version="999", force_install=True))

        assert True

    def test_install_quota_insufficient_space_aborts(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        # GIVEN free space below the install threshold
        mock_disk = MagicMock()
        mock_disk.free = 8 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch.object(install, "_ensure_manifest_for_version", return_value=Path("/nonexistent")),
            patch.object(install, "check_manifestfile_support", return_value=False),
            patch.object(install, "download_depots"),
            pytest.raises(SystemExit),
        ):
            # WHEN downloading without enough space
            # THEN the install aborts
            install.download_version("999", _settings(version="999", force_install=True))

    def test_install_quota_same_manifest_partial_counts(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        # GIVEN a partial download of the same manifest counting toward free space
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "partial_chunk.dat").write_bytes(b"data")
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        mock_disk = MagicMock()
        mock_disk.free = 9 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", manifests_dir),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            patch("os.chown"),
            patch.object(install, "_ensure_manifest_for_version", return_value=Path("/nonexistent")),
            patch.object(install, "check_manifestfile_support", return_value=False),
            patch.object(install, "download_depots"),
        ):
            # WHEN the threshold sits just above free but below free+partial
            # THEN the download proceeds
            install.download_version(
                "999", _settings(version="999", force_install=True, min_free_space=9 * 1024**3 + 1)
            )

        assert True

    def test_install_quota_different_manifest_partial_ignored(
        self,
        tmp_path: Path,
    ) -> None:
        from enshctl import install

        # GIVEN partial data belonging to a different manifest
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        partial_dir = manifests_dir / "888"
        partial_dir.mkdir()
        (partial_dir / "partial_chunk.dat").write_bytes(b"data")

        mock_disk = MagicMock()
        mock_disk.free = 7 * 1024**3

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch("enshctl.install.shutil.disk_usage", return_value=mock_disk),
            pytest.raises(SystemExit),
        ):
            # WHEN downloading with insufficient space
            # THEN the install aborts
            install.download_version("999", _settings(version="999", force_install=True))
