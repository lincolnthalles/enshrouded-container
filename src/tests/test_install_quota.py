"""Tests for install disk space quota checks."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from enshctl import install
from enshctl.download import InstallError
from enshctl.install import DownloadDeps, InstallEnv
from enshctl.settings import AppSettings


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


class TestDownloadVersionQuota:
    """Tests for download_version() disk space checks."""

    def _env(self, free: int) -> InstallEnv:
        return InstallEnv(
            disk_free=lambda _p: free,
            chown=lambda *_args, **_kwargs: None,
            chmod=lambda *_args, **_kwargs: MagicMock(returncode=0),
        )

    def _deps(self, **overrides: object) -> DownloadDeps:
        base: dict[str, object] = {
            "hub_download": lambda _a, _b, _c, _d, _e: Path("/nonexistent"),
            "support": lambda: False,
            "depot_download": lambda _mid, _target, _config: None,
            "discover": lambda: [("2278521", "12345")],
        }
        base.update(overrides)
        return DownloadDeps(**base)  # type: ignore[arg-type]

    def test_install_quota_sufficient_space(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a partially installed manifest and ample free space
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        def _fake_hub_download(_a: str, _b: str, _c: Path, _d: str, _e: str) -> Path:
            path = manifests_dir / "existing.manifest"
            path.write_bytes(b"")
            return path

        # WHEN downloading with sufficient space
        result = install.download_version(
            "999",
            _settings(version="999", force_install=True),
            manifests_dir=manifests_dir,
            env=self._env(12 * 1024**3),
            download=self._deps(hub_download=_fake_hub_download),
        )

        # THEN the install completes
        assert result == target_dir

    def test_install_quota_insufficient_space_aborts(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN free space below the install threshold
        manifests_dir = tmp_path / "manifests"

        # WHEN downloading without enough space
        # THEN the install aborts
        with pytest.raises(InstallError):
            install.download_version(
                "999",
                _settings(version="999", force_install=True),
                manifests_dir=manifests_dir,
                env=self._env(8 * 1024**3),
            )

    def test_install_quota_same_manifest_partial_counts(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a partial download of the same manifest counting toward free space
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "partial_chunk.dat").write_bytes(b"data")
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        # WHEN the threshold sits just above free but below free+partial
        # THEN the download proceeds
        result = install.download_version(
            "999",
            _settings(version="999", force_install=True, min_free_space=9 * 1024**3 + 1),
            manifests_dir=manifests_dir,
            env=self._env(9 * 1024**3),
            download=self._deps(),
        )

        # THEN the partial data counted toward the quota
        assert result == target_dir

    def test_install_quota_different_manifest_partial_ignored(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN partial data belonging to a different manifest
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        partial_dir = manifests_dir / "888"
        partial_dir.mkdir()
        (partial_dir / "partial_chunk.dat").write_bytes(b"data")

        # WHEN downloading with insufficient space
        # THEN the install aborts
        with pytest.raises(InstallError):
            install.download_version(
                "999",
                _settings(version="999", force_install=True),
                manifests_dir=manifests_dir,
                env=self._env(7 * 1024**3),
            )
