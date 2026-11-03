"""Tests for start-command setup wiring and exit codes."""

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

from enshctl.commands import start as start_cmd
from enshctl.config import SaveDirectories
from enshctl.download.types import InstallError
from enshctl.paths import GAME_TREE_DIR, SAVE_DIR
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_start_run_creates_custom_save_dir(tmp_path: Path) -> None:
    # GIVEN a Generated config selecting a custom save directory
    saves = tmp_path / "custom" / "saves"
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.download_flow, "prepare_manifests"),
        patch.object(start_cmd.install, "ensure_install", return_value=tmp_path / "manifests" / "999"),
        patch.object(start_cmd.mods, "build_game_tree"),
        patch.object(start_cmd.config, "generate_config", return_value={"saveDirectory": str(saves)}),
        patch.object(start_cmd.config, "write_config") as mock_write,
        patch.object(start_cmd, "chown") as mock_chown,
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
    ):
        mock_lifecycle.return_value.run.return_value = 0

        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN the configured save directory exists before the server starts
    assert code == 0
    assert saves.is_dir()
    assert mock_chown.call_count >= 1
    assert mock_write.call_count == 1


def test_start_run_resolves_unsafe_save_dir_before_write(tmp_path: Path) -> None:
    # GIVEN a Generated config with an unsafe save directory that resolves to the volume
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))
    new_config = {"saveDirectory": "/data"}

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.download_flow, "prepare_manifests"),
        patch.object(start_cmd.install, "ensure_install", return_value=tmp_path / "manifests" / "999"),
        patch.object(start_cmd.mods, "build_game_tree"),
        patch.object(start_cmd.config, "generate_config", return_value=new_config),
        patch.object(start_cmd.config, "write_config") as mock_write,
        patch.object(start_cmd, "chown"),
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
    ):
        mock_lifecycle.return_value.run.return_value = 0

        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN the Generated config is written once with the safe path
    assert code == 0
    assert new_config["saveDirectory"] == str(SAVE_DIR)
    mock_write.assert_called_once()
    assert mock_write.call_args.args[0]["saveDirectory"] == str(SAVE_DIR)


def test_start_run_warns_on_ownership_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a custom save directory whose ownership cannot be applied
    saves = tmp_path / "custom" / "saves"
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.download_flow, "prepare_manifests"),
        patch.object(start_cmd.install, "ensure_install", return_value=tmp_path / "manifests" / "999"),
        patch.object(start_cmd.mods, "build_game_tree"),
        patch.object(start_cmd.config, "generate_config", return_value={"saveDirectory": str(saves)}),
        patch.object(start_cmd.config, "write_config"),
        patch.object(start_cmd, "chown", side_effect=OSError("nope")),
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
        caplog.at_level("WARNING", logger="enshctl.commands.start"),
    ):
        mock_lifecycle.return_value.run.return_value = 0

        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN the failure is surfaced once without blocking startup
    warnings = [record for record in caplog.records if "Could not set ownership" in record.message]
    assert code == 0
    assert len(warnings) == 1
    assert saves.is_dir()


def test_start_uses_installed_manifest_id(tmp_path: Path) -> None:
    # GIVEN a Version spec that resolves to a different install directory name
    settings = replace(AppSettings(), backup_dir=str(tmp_path / "backups"))

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.download_flow, "prepare_manifests"),
        patch.object(start_cmd.install, "ensure_install", return_value=tmp_path / "manifests" / "999"),
        patch.object(start_cmd.mods, "build_game_tree") as mock_build,
        patch.object(start_cmd.config, "write_generated_config", return_value=SaveDirectories(SAVE_DIR)),
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
    ):
        mock_lifecycle.return_value.run.return_value = 0

        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN the Game tree plan targets the resolved Manifest install
    assert code == 0
    assert mock_build.call_args.args[0].manifest_id == "999"


def test_start_rejects_game_tree_overlapping_backup_dir() -> None:
    # GIVEN a backup directory equal to the Game tree directory
    settings = replace(AppSettings(), backup_dir=str(GAME_TREE_DIR))

    with (
        patch.object(start_cmd, "_setup_directories") as mock_setup,
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN the overlap is rejected before any setup I/O or lifecycle
    assert code == 1
    mock_setup.assert_not_called()
    mock_lifecycle.assert_not_called()


def test_run_returns_one_on_install_error() -> None:
    # GIVEN an Install failure during setup
    settings = AppSettings()

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd, "_prepare_install_and_config", side_effect=InstallError("install failed")),
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN it returns 1 without entering the lifecycle
    assert code == 1
    mock_lifecycle.assert_not_called()


def test_run_returns_lifecycle_code() -> None:
    # GIVEN setup that succeeds
    settings = AppSettings()

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd, "_prepare_install_and_config"),
        patch.object(start_cmd, "ServerLifecycle") as mock_lifecycle,
    ):
        mock_lifecycle.return_value.run.return_value = 7

        # WHEN the start command runs
        code = start_cmd.run(settings)

    # THEN it returns the lifecycle exit code
    assert code == 7
