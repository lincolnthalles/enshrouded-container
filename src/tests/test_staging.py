"""Tests for per-manifest staging through the StagingIO seam."""

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call, patch

from enshctl import staging
from enshctl.config import SaveDirectories
from enshctl.download.types import ManifestRecord
from enshctl.paths import SAVE_DIR
from enshctl.settings import AppSettings
from enshctl.staging import PreparedServer, SystemStagingIO

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class RecordingStagingIO:
    """Records staging calls and returns canned results."""

    def __init__(
        self,
        *,
        installed: Path,
        save_directories: SaveDirectories,
        cached: ManifestRecord | None = None,
    ) -> None:
        self.calls: list[tuple[str, object]] = []
        self._installed = installed
        self._save_directories = save_directories
        self._cached = cached

    def install_version(self, settings: AppSettings) -> Path:
        self.calls.append(("install_version", settings))
        return self._installed

    def install_manifest(self, manifest_id: str, settings: AppSettings) -> Path:
        del settings
        self.calls.append(("install_manifest", manifest_id))
        return self._installed

    def build_game_tree(self, manifest_id: str, settings: AppSettings) -> None:
        del settings
        self.calls.append(("build_game_tree", manifest_id))

    def write_config(self, settings: AppSettings) -> SaveDirectories:
        self.calls.append(("write_config", settings))
        return self._save_directories

    def cached_latest_manifest(self) -> ManifestRecord | None:
        self.calls.append(("cached_latest_manifest", None))
        return self._cached

    def apply_ownership(self, save_directories: SaveDirectories, settings: AppSettings) -> None:
        del settings
        self.calls.append(("apply_ownership", save_directories))


def _recording_io(
    tmp_path: Path,
    *,
    cached: ManifestRecord | None = None,
) -> RecordingStagingIO:
    return RecordingStagingIO(
        installed=tmp_path / "manifests" / "999",
        save_directories=SaveDirectories(tmp_path / "saves"),
        cached=cached,
    )


def test_ensure_installed_delegates_to_install_version(tmp_path: Path) -> None:
    # GIVEN a staging seam whose install returns a Manifest install directory
    settings = AppSettings()
    installed = tmp_path / "manifests" / "999"
    io = RecordingStagingIO(installed=installed, save_directories=SaveDirectories(tmp_path / "saves"))

    # WHEN ensuring the Version spec is installed
    result = staging.ensure_installed(settings, staging_io=io)

    # THEN the Install operation is the only one invoked
    assert result == installed
    assert io.calls == [("install_version", settings)]


def test_stage_sequences_install_tree_config_ownership_and_manifest(tmp_path: Path) -> None:
    # GIVEN a cached Manifest matching the installed Manifest ID
    settings = AppSettings()
    saves = SaveDirectories(tmp_path / "saves")
    cached = ManifestRecord("999", "05/29/2026 12:00:00")
    io = RecordingStagingIO(installed=tmp_path / "manifests" / "999", save_directories=saves, cached=cached)

    # WHEN staging without a pending Manifest
    result = staging.stage(settings, staging_io=io)

    # THEN the full sequence runs in order and the cached Manifest stays active
    assert result == PreparedServer(active_manifest=cached, save_directories=saves)
    assert io.calls == [
        ("install_version", settings),
        ("build_game_tree", "999"),
        ("write_config", settings),
        ("apply_ownership", saves),
        ("cached_latest_manifest", None),
    ]


def test_stage_with_target_installs_pending_manifest_without_resolution(tmp_path: Path) -> None:
    # GIVEN a pending Manifest whose install directory matches its ID
    settings = AppSettings()
    target = ManifestRecord("222", "05/29/2026 13:00:00")
    io = RecordingStagingIO(
        installed=tmp_path / "manifests" / "222",
        save_directories=SaveDirectories(tmp_path / "saves"),
    )

    # WHEN staging the pending Manifest
    result = staging.stage(settings, target=target, staging_io=io)

    # THEN the explicit Manifest is installed and becomes active
    assert result.active_manifest == target
    assert io.calls[0] == ("install_manifest", "222")
    assert ("install_version", settings) not in io.calls
    assert ("build_game_tree", "222") in io.calls


def test_stage_prefers_cached_manifest_over_target(tmp_path: Path) -> None:
    # GIVEN cached and pending Manifests sharing the installed Manifest ID
    settings = AppSettings()
    target = ManifestRecord("999", "05/29/2026 13:00:00")
    cached = ManifestRecord("999", "05/29/2026 12:00:00")
    io = _recording_io(tmp_path, cached=cached)

    # WHEN staging the pending Manifest
    result = staging.stage(settings, target=target, staging_io=io)

    # THEN the cached Manifest wins the reconciliation
    assert result.active_manifest == cached


def test_stage_falls_back_to_installed_manifest_without_timestamp(tmp_path: Path) -> None:
    # GIVEN no cached Manifest and no pending target
    settings = AppSettings()
    io = _recording_io(tmp_path)

    # WHEN staging
    result = staging.stage(settings, staging_io=io)

    # THEN the active Manifest names the installed ID with an empty timestamp
    assert result.active_manifest == ManifestRecord("999", "")


def test_system_install_version_prepares_manifests_before_download(tmp_path: Path) -> None:
    # GIVEN a build Version spec resolved by the default resolver
    settings = replace(AppSettings(), version="build:999")
    installed = tmp_path / "manifests" / "123999"
    io = SystemStagingIO()
    parent = MagicMock()
    parent.resolve.return_value = "123999"
    parent.download.return_value = installed

    with (
        patch("enshctl.staging.download_flow.prepare_manifests", parent.prepare),
        patch("enshctl.staging.manifests.resolve_manifest", parent.resolve),
        patch("enshctl.staging.download_flow.download_version", parent.download),
    ):
        # WHEN installing the Version spec
        result = io.install_version(settings)

    # THEN manifest preparation runs before resolution and the ordered Download
    assert result == installed
    assert parent.mock_calls == [
        call.prepare(settings),
        call.resolve("build:999"),
        call.download("123999", settings, version_spec="build:999"),
    ]


def test_system_install_manifest_skips_version_resolution(tmp_path: Path) -> None:
    # GIVEN a pinned Version spec and an explicit pending Manifest ID
    settings = replace(AppSettings(), version="build:999")
    installed = tmp_path / "manifests" / "999"
    io = SystemStagingIO()

    with (
        patch("enshctl.staging.manifests.resolve_manifest") as mock_resolve,
        patch("enshctl.staging.download_flow.download_version", return_value=installed) as mock_download,
    ):
        # WHEN installing the explicit Manifest
        result = io.install_manifest("999", settings)

    # THEN the explicit ID downloads without re-resolving the Version spec
    assert result == installed
    mock_resolve.assert_not_called()
    mock_download.assert_called_once_with("999", settings, version_spec="latest")


def test_system_staging_apply_ownership_creates_custom_save_dir(tmp_path: Path) -> None:
    # GIVEN a custom Save directory that does not exist yet
    settings = AppSettings()
    saves = tmp_path / "custom" / "saves"
    calls: list[Path] = []

    def record_chown(path: Path, uid: int, gid: int, *, follow_symlinks: bool) -> None:
        calls.append(path)

    io = SystemStagingIO(chown=record_chown)

    # WHEN applying ownership
    io.apply_ownership(SaveDirectories(saves), settings)

    # THEN the Save directory is created and owned
    assert saves.is_dir()
    assert calls == [saves]


def test_system_staging_apply_ownership_warns_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a custom Save directory whose ownership cannot be applied
    settings = AppSettings()
    saves = tmp_path / "custom" / "saves"
    saves.mkdir(parents=True)
    (saves / "world.ksd").write_bytes(b"save")

    def failing_chown(path: Path, uid: int, gid: int, *, follow_symlinks: bool) -> None:
        msg = "not permitted"
        raise OSError(msg)

    io = SystemStagingIO(chown=failing_chown)

    # WHEN applying ownership
    with caplog.at_level("WARNING", logger="enshctl.staging"):
        io.apply_ownership(SaveDirectories(saves), settings)

    # THEN the failure warns once
    warnings = [record for record in caplog.records if "Could not set ownership" in record.message]
    assert len(warnings) == 1


def test_system_staging_apply_ownership_skips_default_save_dir() -> None:
    # GIVEN the default Save directory prepared by the container bootstrap
    calls: list[Path] = []

    def record_chown(path: Path, uid: int, gid: int, *, follow_symlinks: bool) -> None:
        calls.append(path)

    io = SystemStagingIO(chown=record_chown)

    # WHEN applying ownership
    io.apply_ownership(SaveDirectories(SAVE_DIR), AppSettings())

    # THEN staging leaves the default volume ownership untouched
    assert calls == []
