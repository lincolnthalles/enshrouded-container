"""Tests for start-command setup wiring and exit codes."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.commands import start as start_cmd
from enshctl.config import SaveDirectories
from enshctl.download.types import InstallError, ManifestRecord
from enshctl.paths import GAME_TREE_DIR, SAVE_DIR
from enshctl.settings import AppSettings
from enshctl.staging import PreparedServer

if TYPE_CHECKING:
    import pytest


def _prepared(
    manifest: ManifestRecord,
    save_directories: SaveDirectories | None = None,
) -> PreparedServer:
    return PreparedServer(
        active_manifest=manifest,
        save_directories=save_directories or SaveDirectories(SAVE_DIR),
    )


def _seams(
    stage: MagicMock,
    build_lifecycle: MagicMock,
    *,
    cleanup_prune: MagicMock | None = None,
    activate_manifest: MagicMock | None = None,
) -> start_cmd.StartupSeams:
    return start_cmd.StartupSeams(
        stage=stage,
        cleanup_prune=cleanup_prune or MagicMock(),
        activate_manifest=activate_manifest or MagicMock(return_value=None),
        build_lifecycle=build_lifecycle,
    )


def test_start_rejects_game_tree_overlapping_backup_dir() -> None:
    # GIVEN a backup directory equal to the Game tree directory
    settings = replace(AppSettings(), backup_dir=str(GAME_TREE_DIR))
    stage = MagicMock()
    build_lifecycle = MagicMock()

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories") as mock_setup,
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN the overlap is rejected before any setup I/O or staging
    assert code == 1
    mock_setup.assert_not_called()
    stage.assert_not_called()
    build_lifecycle.assert_not_called()


def test_run_returns_one_on_install_error() -> None:
    # GIVEN a staging failure during startup
    settings = AppSettings()
    stage = MagicMock(side_effect=InstallError("install failed"))
    build_lifecycle = MagicMock()

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN it returns 1 without entering the lifecycle
    assert code == 1
    stage.assert_called_once_with(settings)
    build_lifecycle.assert_not_called()


def test_run_returns_lifecycle_code() -> None:
    # GIVEN staging that succeeds
    settings = AppSettings()
    manifest = ManifestRecord("111", "05/29/2026 12:00:00")
    lifecycle = MagicMock()
    lifecycle.run.return_value = 7
    lifecycle.restart_requested = False
    stage = MagicMock(return_value=_prepared(manifest))
    build_lifecycle = MagicMock(return_value=lifecycle)

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN it returns the lifecycle exit code
    assert code == 7
    build_lifecycle.assert_called_once()
    assert build_lifecycle.call_args.kwargs["active_manifest"] == manifest
    assert build_lifecycle.call_args.kwargs["save_directories"] == SaveDirectories(SAVE_DIR)


def test_start_runs_cleanup_then_stage_then_activation() -> None:
    # GIVEN staging that succeeds into one Manifest
    settings = AppSettings()
    manifest = ManifestRecord("111", "05/29/2026 12:00:00")
    lifecycle = MagicMock()
    lifecycle.run.return_value = 0
    lifecycle.restart_requested = False
    manager = MagicMock()
    manager.stage.return_value = _prepared(manifest)
    manager.build_lifecycle.return_value = lifecycle
    manager.activate_manifest.return_value = None
    seams = start_cmd.StartupSeams(
        stage=manager.stage,
        cleanup_prune=manager.cleanup_prune,
        activate_manifest=manager.activate_manifest,
        build_lifecycle=manager.build_lifecycle,
    )

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings, seams=seams)

    # THEN cleanup precedes staging, and activation records the staged Manifest
    assert code == 0
    names = [call[0] for call in manager.method_calls]
    assert names.index("cleanup_prune") < names.index("stage") < names.index("activate_manifest")
    manager.cleanup_prune.assert_called_once_with()
    manager.activate_manifest.assert_called_once()
    args, kwargs = manager.activate_manifest.call_args
    assert args == (settings, "111")
    assert "stop_event" in kwargs


def test_start_relaunches_with_pending_manifest() -> None:
    # GIVEN an update lifecycle that requests a restart into a downloaded Manifest
    settings = replace(AppSettings(), version="latest")
    active = ManifestRecord("111", "05/29/2026 12:00:00")
    target = ManifestRecord("222", "05/29/2026 13:00:00")
    active_saves = SaveDirectories(SAVE_DIR)
    target_saves = SaveDirectories(Path("/mnt/next/saves"))
    first = MagicMock()
    first.run.return_value = 0
    first.restart_requested = True
    first.restart_manifest = target
    second = MagicMock()
    second.run.return_value = 0
    second.restart_requested = False
    stage = MagicMock(side_effect=[_prepared(active, active_saves), _prepared(target, target_saves)])
    build_lifecycle = MagicMock(side_effect=[first, second])

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN the lifecycle relaunches from the pending Manifest
    assert code == 0
    assert build_lifecycle.call_count == 2
    assert build_lifecycle.call_args_list[0].kwargs["active_manifest"] == active
    assert build_lifecycle.call_args_list[1].kwargs["active_manifest"] == target
    assert build_lifecycle.call_args_list[0].kwargs["save_directories"] == active_saves
    assert build_lifecycle.call_args_list[1].kwargs["save_directories"] == target_saves
    assert active_saves != target_saves
    stage.assert_any_call(settings, target=target)


def test_start_returns_one_when_update_relaunch_fails() -> None:
    # GIVEN an update lifecycle whose relaunch staging fails
    settings = replace(AppSettings(), version="latest")
    active = ManifestRecord("111", "05/29/2026 12:00:00")
    target = ManifestRecord("222", "05/29/2026 13:00:00")
    first = MagicMock()
    first.run.return_value = 0
    first.restart_requested = True
    first.restart_manifest = target
    stage = MagicMock(side_effect=[_prepared(active), InstallError("update install failed")])
    build_lifecycle = MagicMock(return_value=first)

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        # WHEN the start command runs
        code = start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN it exits non-zero without a second lifecycle
    assert code == 1
    build_lifecycle.assert_called_once()


def test_start_warns_on_mods_when_auto_update_is_active(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an active latest Auto Update and a populated Mod overlay
    settings = replace(AppSettings(), version="latest")
    manifest = ManifestRecord("111", "05/29/2026 12:00:00")
    lifecycle = MagicMock()
    lifecycle.run.return_value = 0
    lifecycle.restart_requested = False
    stage = MagicMock(return_value=_prepared(manifest))
    build_lifecycle = MagicMock(return_value=lifecycle)

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=(Path("mod.dll"),)),
        caplog.at_level("WARNING", logger="enshctl.commands.start"),
    ):
        # WHEN the start command runs
        start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN the mod compatibility warning is logged
    assert any("may break mods" in record.message for record in caplog.records)


def test_start_skips_mod_warning_when_auto_update_is_inactive(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a pinned Version spec and a populated Mod overlay
    settings = replace(AppSettings(), version="123")
    manifest = ManifestRecord("123", "05/29/2026 12:00:00")
    lifecycle = MagicMock()
    lifecycle.run.return_value = 0
    lifecycle.restart_requested = False
    stage = MagicMock(return_value=_prepared(manifest))
    build_lifecycle = MagicMock(return_value=lifecycle)

    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=(Path("mod.dll"),)),
        caplog.at_level("WARNING", logger="enshctl.commands.start"),
    ):
        # WHEN the start command runs
        start_cmd.run(settings, seams=_seams(stage, build_lifecycle))

    # THEN no mod compatibility warning is logged
    assert not any("may break mods" in record.message for record in caplog.records)
