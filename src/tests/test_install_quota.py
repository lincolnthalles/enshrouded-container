"""Tests for install disk space quota checks."""

import os
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from enshctl import manifest_retention
from enshctl.disk_space import SpaceGuard
from enshctl.download.flow import download_version
from enshctl.download.io import DownloadIO, HostIO
from enshctl.download.types import InstallError
from enshctl.paths import DEPOT_ID, STATUS_FILE
from enshctl.settings import AppSettings


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


def _host(free: int = 12 * 1024**3) -> MagicMock:
    host = MagicMock(spec=HostIO)
    host.space = SpaceGuard(disk_free=lambda _p: free)
    host.is_file.side_effect = Path.is_file
    host.is_symlink.side_effect = Path.is_symlink
    host.mkdir.side_effect = lambda path: path.mkdir(parents=True, exist_ok=True)
    host.touch.side_effect = Path.touch
    return host


def _download() -> MagicMock:
    download = MagicMock(spec=DownloadIO)
    download.supports_manifestfile.return_value = True
    download.discover_depots.return_value = [(DEPOT_ID, "12345")]

    def _write_exe(_mid: str, target: Path, _config: object, _pinned: object = None) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / "enshrouded_server.exe").write_bytes(b"")

    download.download_depots.side_effect = _write_exe
    return download


class TestDownloadVersionQuota:
    """Tests for download_version() disk space checks."""

    def test_install_quota_sufficient_space(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a partially installed manifest and ample free space
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / "enshrouded_server.exe").write_bytes(b"")

        # WHEN downloading with sufficient space
        result = download_version(
            "999",
            _settings(version="999", force_install=True),
            manifests_dir=manifests_dir,
            host=cast("HostIO", _host(12 * 1024**3)),
            source=cast("DownloadIO", _download()),
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
            download_version(
                "999",
                _settings(version="999", force_install=True),
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host(8 * 1024**3)),
                source=cast("DownloadIO", _download()),
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
        result = download_version(
            "999",
            _settings(version="999", force_install=True, min_free_space=9 * 1024**3 + 1),
            manifests_dir=manifests_dir,
            host=cast("HostIO", _host(9 * 1024**3)),
            source=cast("DownloadIO", _download()),
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
            download_version(
                "999",
                _settings(version="999", force_install=True),
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host(7 * 1024**3)),
                source=cast("DownloadIO", _download()),
            )


def _complete_install(manifests_dir: Path, manifest_id: str, mtime_ns: int) -> Path:
    path = manifests_dir / manifest_id
    path.mkdir(parents=True)
    (path / "game.bin").write_bytes(b"game")
    marker = path / STATUS_FILE
    marker.touch()
    os.utime(marker, ns=(mtime_ns, mtime_ns))
    return path


def _host_reclaiming(manifests_dir: Path, old_id: str, *, free_before: int, free_after: int) -> MagicMock:
    host = _host(free_before)
    host.space = SpaceGuard(
        disk_free=lambda _p: free_after if not (manifests_dir / old_id).exists() else free_before,
    )
    return host


class TestDownloadVersionReclamation:
    """Tests for pre-download reclamation of older Manifest installs."""

    def test_reclaimed_backlog_lets_download_proceed(self, tmp_path: Path) -> None:
        # GIVEN two older complete installs and free space below the threshold
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        _complete_install(manifests_dir, "100", 1_000)
        _complete_install(manifests_dir, "200", 2_000)
        host = _host_reclaiming(manifests_dir, "100", free_before=5 * 1024**3, free_after=15 * 1024**3)
        game_tree_dir = tmp_path / "gameserver"
        game_tree_dir.mkdir()

        # WHEN downloading a latest-tracking Manifest with insufficient space
        result = download_version(
            "999",
            _settings(version="latest", force_install=True),
            manifests_dir=manifests_dir,
            host=cast("HostIO", host),
            source=cast("DownloadIO", _download()),
            game_tree_dir=game_tree_dir,
        )

        # THEN the oldest install is reclaimed, the fallback remains, and the download proceeds
        assert result == manifests_dir / "999"
        assert not (manifests_dir / "100").exists()
        assert (manifests_dir / "200").is_dir()

    def test_reclamation_failure_still_aborts(self, tmp_path: Path) -> None:
        # GIVEN two older complete installs and space that stays short after reclaiming
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        _complete_install(manifests_dir, "100", 1_000)
        _complete_install(manifests_dir, "200", 2_000)
        game_tree_dir = tmp_path / "gameserver"
        game_tree_dir.mkdir()

        # WHEN downloading with no room even after reclamation
        # THEN the install aborts after attempting reclamation
        with pytest.raises(InstallError):
            download_version(
                "999",
                _settings(version="latest", force_install=True),
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host(5 * 1024**3)),
                source=cast("DownloadIO", _download()),
                game_tree_dir=game_tree_dir,
            )
        assert not (manifests_dir / "100").exists()
        assert (manifests_dir / "200").is_dir()

    def test_disabled_pruning_skips_reclamation(self, tmp_path: Path) -> None:
        # GIVEN older complete installs and pruning disabled
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        _complete_install(manifests_dir, "100", 1_000)
        _complete_install(manifests_dir, "200", 2_000)

        # WHEN downloading with insufficient space
        # THEN the install aborts without deleting anything
        with pytest.raises(InstallError):
            download_version(
                "999",
                _settings(version="latest", force_install=True, manifest_prune_enabled=False),
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host(5 * 1024**3)),
                source=cast("DownloadIO", _download()),
            )
        assert (manifests_dir / "100").is_dir()
        assert (manifests_dir / "200").is_dir()

    def test_pinned_version_skips_reclamation(self, tmp_path: Path) -> None:
        # GIVEN older complete installs and an explicit Version spec
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        _complete_install(manifests_dir, "100", 1_000)
        _complete_install(manifests_dir, "200", 2_000)

        # WHEN downloading with insufficient space
        # THEN the install aborts without deleting anything
        with pytest.raises(InstallError):
            download_version(
                "999",
                _settings(version="999", force_install=True),
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host(5 * 1024**3)),
                source=cast("DownloadIO", _download()),
            )
        assert (manifests_dir / "100").is_dir()
        assert (manifests_dir / "200").is_dir()


class TestDownloadVersionCleanup:
    """Tests for staging cleanup ordering before disk-space evaluation."""

    def test_cleanup_precedes_initial_space_evaluation(self, tmp_path: Path) -> None:
        # GIVEN staged prune data and ample free space
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
        prune_dir.mkdir()
        stale = prune_dir / "100"
        stale.mkdir()
        (stale / "game.bin").write_bytes(b"stale")
        observed: list[bool] = []
        host = _host(12 * 1024**3)
        host.space = SpaceGuard(
            disk_free=lambda _p: (observed.append(stale.exists()), 12 * 1024**3)[1],
        )

        # WHEN downloading a Manifest with sufficient space
        result = download_version(
            "999",
            _settings(version="latest", force_install=True),
            manifests_dir=manifests_dir,
            host=cast("HostIO", host),
            source=cast("DownloadIO", _download()),
        )

        # THEN cleanup completed before the initial free-space evaluation
        assert result == manifests_dir / "999"
        assert observed == [False]
        assert not stale.exists()


class TestDownloadVersionLifecycle:
    """Tests for the installed marker and ownership behavior."""

    def test_installed_version_skips_download(self, tmp_path: Path) -> None:
        # GIVEN an installed version marker and server binary
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (target_dir / STATUS_FILE).write_bytes(b"")
        (target_dir / "enshrouded_server.exe").write_bytes(b"")
        host = _host()
        download = _download()

        # WHEN downloading without force
        result = download_version(
            "999",
            _settings(version="999"),
            manifests_dir=manifests_dir,
            host=cast("HostIO", host),
            source=cast("DownloadIO", download),
        )

        # THEN no download, probe, or ownership work runs
        assert result == target_dir
        download.download_depots.assert_not_called()
        download.supports_manifestfile.assert_not_called()
        host.chown.assert_not_called()

    def test_missing_server_binary_fails_without_marker(self, tmp_path: Path) -> None:
        # GIVEN a download that produces no server binary
        manifests_dir = tmp_path / "manifests"
        host = _host()
        download = _download()
        download.download_depots.side_effect = None

        # WHEN downloading
        # THEN the install fails before writing the marker
        with pytest.raises(InstallError, match="not found"):
            download_version(
                "999",
                _settings(version="999", force_install=True, min_free_space=0),
                manifests_dir=manifests_dir,
                host=cast("HostIO", host),
                source=cast("DownloadIO", download),
            )
        assert not (manifests_dir / "999" / STATUS_FILE).exists()

    def test_chown_failure_is_install_error(self, tmp_path: Path) -> None:
        # GIVEN a host that cannot change ownership
        host = _host()
        host.chown.side_effect = OSError("boom")

        # WHEN downloading
        # THEN the ownership failure is a descriptive install error
        with pytest.raises(InstallError, match="ownership"):
            download_version(
                "999",
                _settings(version="999", force_install=True, min_free_space=0),
                manifests_dir=tmp_path / "manifests",
                host=cast("HostIO", host),
                source=cast("DownloadIO", _download()),
            )

    def test_chown_targets_only_version_dir(self, tmp_path: Path) -> None:
        # GIVEN a successful download
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        host = _host()
        settings = _settings(version="999", force_install=True, min_free_space=0)

        # WHEN downloading
        download_version(
            "999",
            settings,
            manifests_dir=manifests_dir,
            host=cast("HostIO", host),
            source=cast("DownloadIO", _download()),
        )

        # THEN only the version directory is chowned
        host.chown.assert_called_once_with(target_dir, uid=settings.puid, gid=settings.pgid)


def test_system_host_make_readonly(tmp_path: Path) -> None:
    from enshctl.download.io import SystemHostIO

    # GIVEN a system host adapter
    host = SystemHostIO()

    # WHEN marking an install read-only
    with patch("enshctl.download.io.subprocess.run") as mock_run:
        host.make_readonly(tmp_path)

    # THEN chmod runs recursively on that path
    mock_run.assert_called_once_with(["chmod", "-R", "a-w", str(tmp_path)], check=False)
