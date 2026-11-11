"""Tests for the auto rollback controller, selection, and startup restore."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.backup_protocol import Trigger
from enshctl.commands import start as start_cmd
from enshctl.config import SaveDirectories
from enshctl.download.types import ManifestRecord
from enshctl.lifecycle.rollback import (
    RollbackController,
    describe_startup,
    format_next_run,
    is_rollback_active,
    is_rollback_scheduled,
    resolve_rollback_backup,
    restore_at_startup,
    restore_for_restart,
    rollback_interval,
)
from enshctl.lifecycle.runtime import ServerLifecycle, exit_server
from enshctl.lifecycle.types import ExitRequest
from enshctl.paths import SAVE_DIR
from enshctl.restore_flow import RestoreIO, RestoreOutcome
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    import pytest
    from enshctl.disk_space import SpaceGuard


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


class _FakeLock:
    def __init__(self, fd: int | None = 3) -> None:
        self._fd = fd

    def acquire(self, path: Path, wait_seconds: int = 0) -> int | None:
        del path, wait_seconds
        return self._fd

    def release(self, fd: int) -> None:
        del fd


class _RecordingChown:
    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[tuple[Path, ...], int, int]] = []

    def __call__(self, *paths: Path, uid: int, gid: int) -> None:
        self.calls.append((paths, uid, gid))
        if self.error is not None:
            raise self.error


class _RecordingRestore:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(
        self,
        backup_path: Path,
        *,
        saves_dir: Path,
        tmp_dir: Path,
        space: SpaceGuard,
    ) -> None:
        del saves_dir, tmp_dir, space
        self.calls.append(backup_path)


def test_rollback_disabled_by_default() -> None:
    # GIVEN default settings
    # WHEN checking rollback activity
    # THEN neither active nor scheduled applies
    assert is_rollback_active(AppSettings()) is False
    assert is_rollback_scheduled(AppSettings()) is False


def test_rollback_scheduled_needs_cron() -> None:
    # GIVEN rollback enabled with and without a schedule
    scheduled = _settings(rollback_enabled=True, rollback_file="b.tar.zst", rollback_cron="*/30 * * * *")
    startup_only = _settings(rollback_enabled=True, rollback_file="b.tar.zst", rollback_cron="")

    # WHEN checking the schedule gate
    # THEN only the cron mode schedules a loop
    assert is_rollback_scheduled(scheduled) is True
    assert is_rollback_scheduled(startup_only) is False


def test_rollback_interval_falls_back_on_bad_cron() -> None:
    # GIVEN enabled rollback with a malformed schedule
    settings = _settings(rollback_enabled=True, rollback_file="b.tar.zst", rollback_cron="not-a-cron")

    # WHEN computing the next tick
    # THEN the 3600s fallback applies
    assert rollback_interval(settings) == 3600.0


def test_format_next_run_counts_down() -> None:
    # GIVEN wall-clock countdowns
    # WHEN formatting the next run
    # THEN hour and minute buckets are humanized
    assert format_next_run(3600.0) == "in 1h"
    assert format_next_run(5400.0) == "in 1h 30m"
    assert format_next_run(120.0) == "in 2m"


def test_describe_startup_names_mode() -> None:
    # GIVEN startup-only and scheduled configurations
    startup_only = _settings(rollback_enabled=True, rollback_file="base.tar.zst", rollback_cron="")
    scheduled = _settings(rollback_enabled=True, rollback_file="base.tar.zst", rollback_cron="*/60 * * * *")

    # WHEN describing startup
    # THEN the mode and file are named
    assert "base.tar.zst" in describe_startup(startup_only)
    assert "on next restart" in describe_startup(startup_only)
    assert "base.tar.zst" in describe_startup(scheduled)
    assert "next run" in describe_startup(scheduled)


def test_resolve_rollback_searches_every_category(tmp_path: Path) -> None:
    # GIVEN a cold Backup and no live copy
    settings = _settings(rollback_enabled=True, rollback_file="enshrouded-20260529-120000-cold.tar.zst")
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    cold = tmp_path / "backups" / "cold" / settings.rollback_file
    cold.parent.mkdir(parents=True)
    cold.write_bytes(b"backup")

    # WHEN resolving the rollback file
    # THEN the cold Category copy is selected
    assert resolve_rollback_backup(settings) == cold


def test_resolve_rollback_rejects_escape() -> None:
    # GIVEN a traversal filename
    settings = _settings(rollback_enabled=True, rollback_file="../escape.tar.zst")

    # WHEN resolving the rollback file
    # THEN no match is returned
    assert resolve_rollback_backup(settings) is None


def test_restore_at_startup_ignores_when_disabled(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN rollback disabled with file and cron left configured for future use
    settings = _settings(rollback_enabled=False, rollback_file="b.tar.zst", rollback_cron="*/30 * * * *")

    # WHEN running the startup restore
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.rollback"):
        outcome = restore_at_startup(settings, SaveDirectories(Path("/tmp/saves")))

    # THEN nothing runs and nothing is logged
    assert outcome is None
    assert caplog.records == []


def test_restore_at_startup_fails_without_file() -> None:
    # GIVEN rollback enabled with no file
    settings = _settings(rollback_enabled=True, rollback_file="")

    # WHEN running the startup restore
    outcome = restore_at_startup(settings, SaveDirectories(Path("/tmp/saves")))

    # THEN it reports an error without touching saves
    assert outcome is RestoreOutcome.ERROR


def test_restore_at_startup_reports_unknown_file(tmp_path: Path) -> None:
    # GIVEN rollback enabled with an unknown filename
    settings = _settings(rollback_enabled=True, rollback_file="missing.tar.zst")
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))

    # WHEN running the startup restore
    outcome = restore_at_startup(settings, SaveDirectories(tmp_path / "saves"))

    # THEN it reports an error
    assert outcome is RestoreOutcome.ERROR


def test_restore_at_startup_restores_selected_backup(tmp_path: Path) -> None:
    # GIVEN an enabled rollback file present in the cold Category
    filename = "enshrouded-20260529-120000-cold.tar.zst"
    settings = _settings(rollback_enabled=True, rollback_file=filename)
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "cold" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    restore = _RecordingRestore()
    restore_io = RestoreIO(lock=_FakeLock(), restore=restore)  # type: ignore[arg-type]

    # WHEN running the startup restore
    outcome = restore_at_startup(settings, SaveDirectories(tmp_path / "saves"), restore_io=restore_io)

    # THEN the selected Backup is restored through the lock
    assert outcome is RestoreOutcome.SUCCESS
    assert restore.calls == [backup_path]


def test_restore_at_startup_reports_lock_held(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an enabled rollback file with the backup lock held
    filename = "enshrouded-20260529-120000-cold.tar.zst"
    settings = _settings(rollback_enabled=True, rollback_file=filename)
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "cold" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    restore_io = RestoreIO(lock=_FakeLock(fd=None), restore=_RecordingRestore())  # type: ignore[arg-type]

    # WHEN running the startup restore
    with caplog.at_level("ERROR", logger="enshctl.lifecycle.rollback"):
        outcome = restore_at_startup(settings, SaveDirectories(tmp_path / "saves"), restore_io=restore_io)

    # THEN the held lock is reported naming the Backup file
    assert outcome is RestoreOutcome.LOCK_HELD
    assert any(filename in record.message for record in caplog.records)


def test_controller_requests_one_restart(tmp_path: Path) -> None:
    # GIVEN a scheduled controller whose wall-clock tick is already due with a valid Backup
    filename = "enshrouded-20260529-120000.tar.zst"
    settings = _settings(rollback_enabled=True, rollback_file=filename, rollback_cron="*/60 * * * *")
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "live" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    requested = threading.Event()
    stop = threading.Event()
    times = iter([0.0, 10000.0, 10000.0, 10000.0])

    def _clock() -> float:
        return next(times, 10000.0)

    controller = RollbackController(
        settings, requested, clock=_clock, wait=lambda _event, _timeout: False, lock=_FakeLock()
    )

    # WHEN starting the public controller contract
    thread = controller.start(stop)
    thread.join(timeout=2)

    # THEN one restart is requested and the loop exits
    assert requested.is_set()
    assert thread.is_alive() is False


def test_controller_skips_tick_without_matching_backup(tmp_path: Path) -> None:
    # GIVEN a scheduled tick with an unknown rollback file
    settings = _settings(rollback_enabled=True, rollback_file="missing.tar.zst", rollback_cron="*/60 * * * *")
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    requested = threading.Event()
    stop = threading.Event()
    times = iter([0.0, 10000.0, 10000.0])

    def _clock() -> float:
        return next(times, 10000.0)

    waits = 0

    def _wait(event: threading.Event, timeout: float) -> bool:
        nonlocal waits
        del timeout
        waits += 1
        if waits >= 2:
            stop.set()
            return True
        return event.is_set()

    controller = RollbackController(settings, requested, clock=_clock, wait=_wait, lock=_FakeLock())

    # WHEN starting the public controller contract
    thread = controller.start(stop)
    thread.join(timeout=2)

    # THEN no restart is requested and the server keeps running
    assert requested.is_set() is False


def test_controller_skips_tick_when_lock_held(tmp_path: Path) -> None:
    # GIVEN a scheduled tick with the backup lock held
    filename = "enshrouded-20260529-120000.tar.zst"
    settings = _settings(
        rollback_enabled=True,
        rollback_file=filename,
        rollback_cron="*/60 * * * *",
        shutdown_backup_wait=0,
    )
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "live" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    requested = threading.Event()
    stop = threading.Event()
    times = iter([0.0, 10000.0, 10000.0, 10000.0])

    def _clock() -> float:
        return next(times, 10000.0)

    waits = 0

    def _wait(event: threading.Event, timeout: float) -> bool:
        nonlocal waits
        del timeout
        waits += 1
        if waits >= 2:
            stop.set()
            return True
        return event.is_set()

    controller = RollbackController(settings, requested, clock=_clock, wait=_wait, lock=_FakeLock(fd=None))

    # WHEN starting the public controller contract
    thread = controller.start(stop)
    thread.join(timeout=2)

    # THEN no restart is requested and the server keeps running
    assert requested.is_set() is False


def test_restore_for_restart_waits_for_lock(tmp_path: Path) -> None:
    # GIVEN an enabled rollback file with a lock that clears
    filename = "enshrouded-20260529-120000.tar.zst"
    settings = _settings(rollback_enabled=True, rollback_file=filename, shutdown_backup_wait=5)
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "live" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    restore = _RecordingRestore()

    class _WaitingLock:
        def __init__(self) -> None:
            self.waits: list[int] = []

        def acquire(self, _path: Path, wait_seconds: int = 0) -> int | None:
            self.waits.append(wait_seconds)
            return 3

        def release(self, _fd: int) -> None:
            return None

    lock = _WaitingLock()
    restore_io = RestoreIO(lock=lock, restore=restore)  # type: ignore[arg-type]

    # WHEN restoring between stop and relaunch
    outcome = restore_for_restart(settings, SaveDirectories(tmp_path / "saves"), restore_io=restore_io)

    # THEN the shutdown wait budget crosses the seam and the Backup restores
    assert outcome is RestoreOutcome.SUCCESS
    assert lock.waits == [5]
    assert restore.calls == [backup_path]


def test_rollback_suppresses_shutdown_backup() -> None:
    # GIVEN rollback active with cold backups otherwise enabled
    events: list[object] = []

    class _Process:
        pid: int = 1
        stdout: object = None

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def send_signal(self, _sig: int) -> None:
            return None

        def kill(self) -> None:
            return None

    class _Control:
        def signal_game(self, _sig: int) -> bool:
            events.append("signal")
            return True

        def signal_pid(self, _pid: int, _sig: int) -> bool:
            return True

        def wine_tree(self) -> None:
            return None

        def suspend_all(self) -> bool:
            return True

        def resume_all(self) -> bool:
            return True

        def stream(self, _process: object, *, on_line: object = None) -> threading.Thread:
            del on_line
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_log_tail(self, _stop: threading.Event) -> threading.Thread:
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_resource_poller(self, _pid: int, _stop: threading.Event, *, pause_gate: object) -> None:
            del pause_gate

    class _IO:
        def backup_needed(self) -> bool:
            return True

        def run_backup(self, _request: object) -> None:
            events.append("backup")

        def start_scheduler(self, _stop: threading.Event, *, pause_gate: object) -> threading.Thread:
            del pause_gate
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_updater(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def start_rollback(self, _request: threading.Event, _stop: threading.Event) -> None:
            return None

        def cleanup_wine(self) -> None:
            events.append("wine")

        def write_pid(self, _pid: int) -> None:
            return None

        def clear_pid(self) -> None:
            events.append("clear_pid")

    # WHEN the shutdown exit path runs
    settings = replace(
        AppSettings(),
        rollback_enabled=True,
        rollback_file="b.tar.zst",
        backup_cold=True,
        backup_emergency=True,
    )
    code = exit_server(
        ExitRequest(Trigger.SHUTDOWN, 0),
        settings=settings,
        process_handle=_Process(),  # type: ignore[arg-type]
        stop_event=threading.Event(),
        process_control=_Control(),  # type: ignore[arg-type]
        lifecycle_io=_IO(),  # type: ignore[arg-type]
    )

    # THEN no backup runs while cleanup still does
    assert code == 0
    assert "backup" not in events
    assert "wine" in events


def test_rollback_skips_scheduler_and_starts_rollback() -> None:
    # GIVEN rollback active with live backups otherwise enabled
    events: list[object] = []

    class _Process:
        pid: int = 4321
        stdout: object = None

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def send_signal(self, _sig: int) -> None:
            return None

        def kill(self) -> None:
            return None

    class _Control:
        def start(self) -> object:
            events.append("start")
            return _Process()

        def signal_game(self, _sig: int) -> bool:
            return True

        def signal_pid(self, _pid: int, _sig: int) -> bool:
            return True

        def wine_tree(self) -> None:
            return None

        def suspend_all(self) -> bool:
            return True

        def resume_all(self) -> bool:
            return True

        def stream(self, _process: object, *, on_line: object = None) -> threading.Thread:
            del on_line
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_log_tail(self, _stop: threading.Event) -> threading.Thread:
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_resource_poller(self, _pid: int, _stop: threading.Event, *, pause_gate: object) -> None:
            del pause_gate

    class _IO:
        scheduler_started: bool
        rollback_started: bool

        def __init__(self) -> None:
            self.scheduler_started = False
            self.rollback_started = False

        def backup_needed(self) -> bool:
            return False

        def run_backup(self, _request: object) -> None:
            return None

        def start_scheduler(self, _stop: threading.Event, *, pause_gate: object) -> threading.Thread:
            del pause_gate
            self.scheduler_started = True
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_updater(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def start_rollback(self, _request: threading.Event, _stop: threading.Event) -> threading.Thread | None:
            self.rollback_started = True
            return None

        def cleanup_wine(self) -> None:
            return None

        def write_pid(self, _pid: int) -> None:
            return None

        def clear_pid(self) -> None:
            return None

    settings = _settings(
        rollback_enabled=True,
        rollback_file="b.tar.zst",
        rollback_cron="*/30 * * * *",
        backup_live=True,
        backup_cold=False,
        backup_emergency=False,
    )
    io = _IO()

    # WHEN the lifecycle runs to an immediate exit
    with patch("enshctl.lifecycle.runtime.signal.signal"):
        code = ServerLifecycle(
            settings,
            process_control=_Control(),  # type: ignore[arg-type]
            lifecycle_io=io,  # type: ignore[arg-type]
            save_directories=SaveDirectories(SAVE_DIR),
        ).run()

    # THEN the scheduler is suppressed while the rollback loop starts
    assert code == 0
    assert io.scheduler_started is False
    assert io.rollback_started is True


def test_startup_restore_failure_aborts_launch() -> None:
    # GIVEN rollback enabled with an unknown file
    settings = _settings(rollback_enabled=True, rollback_file="missing.tar.zst")
    manifest = ManifestRecord("111", "05/29/2026 12:00:00")
    stage = MagicMock(
        return_value=MagicMock(active_manifest=manifest, save_directories=SaveDirectories(Path("/tmp/saves")))
    )
    build_lifecycle = MagicMock()
    seams = start_cmd.StartupSeams(
        stage=stage,
        cleanup_prune=MagicMock(),
        activate_manifest=MagicMock(return_value=None),
        build_lifecycle=build_lifecycle,
    )

    # WHEN the start command runs
    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
    ):
        code = start_cmd.run(settings, seams=seams)

    # THEN it exits non-zero without launching
    assert code == 1
    build_lifecycle.assert_not_called()


def test_scheduled_rollback_relaunches_after_restore() -> None:
    # GIVEN a lifecycle that requests a rollback restart
    settings = _settings(rollback_enabled=True, rollback_file="b.tar.zst", rollback_cron="*/30 * * * *")
    active = ManifestRecord("111", "05/29/2026 12:00:00")
    first = MagicMock()
    first.run.return_value = 0
    first.restart_requested = False
    first.rollback_requested = True
    first.restart_manifest = None
    second = MagicMock()
    second.run.return_value = 0
    second.restart_requested = False
    second.rollback_requested = False
    stage = MagicMock(
        side_effect=[
            MagicMock(active_manifest=active, save_directories=SaveDirectories(SAVE_DIR)),
            MagicMock(active_manifest=active, save_directories=SaveDirectories(SAVE_DIR)),
        ]
    )
    build_lifecycle = MagicMock(side_effect=[first, second])
    scheduled_restore = MagicMock(return_value=RestoreOutcome.SUCCESS)
    seams = start_cmd.StartupSeams(
        stage=stage,
        cleanup_prune=MagicMock(),
        activate_manifest=MagicMock(return_value=None),
        build_lifecycle=build_lifecycle,
        startup_restore=MagicMock(return_value=RestoreOutcome.SUCCESS),
        scheduled_restore=scheduled_restore,
    )

    # WHEN the start command runs
    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        code = start_cmd.run(settings, seams=seams)

    # THEN the rollback restore runs between lifecycles and the server relaunches
    assert code == 0
    assert build_lifecycle.call_count == 2
    assert scheduled_restore.call_count == 1


def test_failed_scheduled_restore_still_relaunches() -> None:
    # GIVEN a rollback tick whose restore fails after the stop
    settings = _settings(rollback_enabled=True, rollback_file="b.tar.zst", rollback_cron="*/30 * * * *")
    active = ManifestRecord("111", "05/29/2026 12:00:00")
    first = MagicMock()
    first.run.return_value = 0
    first.restart_requested = False
    first.rollback_requested = True
    first.restart_manifest = None
    second = MagicMock()
    second.run.return_value = 0
    second.restart_requested = False
    second.rollback_requested = False
    stage = MagicMock(
        side_effect=[
            MagicMock(active_manifest=active, save_directories=SaveDirectories(SAVE_DIR)),
            MagicMock(active_manifest=active, save_directories=SaveDirectories(SAVE_DIR)),
        ]
    )
    build_lifecycle = MagicMock(side_effect=[first, second])
    seams = start_cmd.StartupSeams(
        stage=stage,
        cleanup_prune=MagicMock(),
        activate_manifest=MagicMock(return_value=None),
        build_lifecycle=build_lifecycle,
        startup_restore=MagicMock(return_value=RestoreOutcome.SUCCESS),
        scheduled_restore=MagicMock(return_value=RestoreOutcome.ERROR),
    )

    # WHEN the start command runs
    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        code = start_cmd.run(settings, seams=seams)

    # THEN the server still relaunches on the pre-rollback saves
    assert code == 0
    assert build_lifecycle.call_count == 2


def test_resolve_rollback_rejects_absolute_and_directory(tmp_path: Path) -> None:
    # GIVEN an absolute path and a directory entry
    base = tmp_path / "backups"
    (base / "live").mkdir(parents=True)
    directory = base / "live" / "adir"
    directory.mkdir()
    absolute_settings = _settings(rollback_enabled=True, rollback_file="/data/backups/live/b.tar.zst")
    absolute_settings = replace(absolute_settings, backup_dir=str(base))
    dir_settings = _settings(rollback_enabled=True, rollback_file="adir")
    dir_settings = replace(dir_settings, backup_dir=str(base))

    # WHEN resolving the rollback file
    # THEN both report no match
    assert resolve_rollback_backup(absolute_settings) is None
    assert resolve_rollback_backup(dir_settings) is None


def test_combined_update_and_rollback_relaunch_once() -> None:
    # GIVEN a rollback tick coinciding with a pending update Manifest
    settings = _settings(rollback_enabled=True, rollback_file="b.tar.zst", rollback_cron="*/30 * * * *")
    active = ManifestRecord("111", "05/29/2026 12:00:00")
    target = ManifestRecord("222", "05/29/2026 13:00:00")
    first = MagicMock()
    first.run.return_value = 0
    first.restart_requested = True
    first.rollback_requested = True
    first.restart_manifest = target
    second = MagicMock()
    second.run.return_value = 0
    second.restart_requested = False
    second.rollback_requested = False
    stage = MagicMock(
        side_effect=[
            MagicMock(active_manifest=active, save_directories=SaveDirectories(SAVE_DIR)),
            MagicMock(active_manifest=target, save_directories=SaveDirectories(SAVE_DIR)),
        ]
    )
    build_lifecycle = MagicMock(side_effect=[first, second])
    scheduled_restore = MagicMock(return_value=RestoreOutcome.SUCCESS)
    seams = start_cmd.StartupSeams(
        stage=stage,
        cleanup_prune=MagicMock(),
        activate_manifest=MagicMock(return_value=None),
        build_lifecycle=build_lifecycle,
        startup_restore=MagicMock(return_value=RestoreOutcome.SUCCESS),
        scheduled_restore=scheduled_restore,
    )

    # WHEN the start command runs
    with (
        patch.object(start_cmd, "_setup_timezone"),
        patch.object(start_cmd, "_setup_directories"),
        patch.object(start_cmd, "_setup_x11_socket"),
        patch.object(start_cmd, "ensure_prefix"),
        patch.object(start_cmd.mods, "mod_files", return_value=()),
    ):
        code = start_cmd.run(settings, seams=seams)

    # THEN one combined relaunch restores and uses the pending Manifest
    assert code == 0
    assert build_lifecycle.call_count == 2
    assert scheduled_restore.call_count == 1
    assert stage.call_args_list[1].kwargs == {"target": target}


def test_rollback_stop_failure_exits_without_relaunch() -> None:
    # GIVEN a rollback restart whose server never stops
    events: list[object] = []

    class _StuckProcess:
        pid: int = 4321
        stdout: object = None

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def send_signal(self, _sig: int) -> None:
            return None

        def kill(self) -> None:
            return None

    class _Control:
        def signal_game(self, _sig: int) -> bool:
            events.append("signal")
            return False

        def signal_pid(self, _pid: int, _sig: int) -> bool:
            return False

        def wine_tree(self) -> None:
            return None

        def suspend_all(self) -> bool:
            return True

        def resume_all(self) -> bool:
            return True

        def stream(self, _process: object, *, on_line: object = None) -> threading.Thread:
            del on_line
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_log_tail(self, _stop: threading.Event) -> threading.Thread:
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_resource_poller(self, _pid: int, _stop: threading.Event, *, pause_gate: object) -> None:
            del pause_gate

    class _IO:
        def backup_needed(self) -> bool:
            return False

        def run_backup(self, _request: object) -> None:
            events.append("backup")

        def start_scheduler(self, _stop: threading.Event, *, pause_gate: object) -> threading.Thread:
            del pause_gate
            thread = threading.Thread(target=lambda: None)
            thread.start()
            return thread

        def start_updater(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def start_rollback(self, _request: threading.Event, _stop: threading.Event) -> None:
            return None

        def cleanup_wine(self) -> None:
            events.append("wine")

        def write_pid(self, _pid: int) -> None:
            events.append("write_pid")

        def clear_pid(self) -> None:
            events.append("clear_pid")

    settings = _settings(
        rollback_enabled=True,
        rollback_file="b.tar.zst",
        backup_cold=False,
        backup_emergency=False,
    )

    # WHEN the rollback exit path cannot stop the server
    code = exit_server(
        ExitRequest(Trigger.ROLLBACK, 0),
        settings=settings,
        process_handle=_StuckProcess(),  # type: ignore[arg-type]
        stop_event=threading.Event(),
        process_control=_Control(),  # type: ignore[arg-type]
        lifecycle_io=_IO(),  # type: ignore[arg-type]
    )

    # THEN it exits non-zero without cleanup or relaunch
    assert code == 1
    assert "wine" not in events
    assert "clear_pid" not in events
    assert "backup" not in events


def test_restore_at_startup_applies_save_ownership(tmp_path: Path) -> None:
    # GIVEN an enabled rollback file and a successful restore
    filename = "enshrouded-20260529-120000.tar.zst"
    settings = _settings(rollback_enabled=True, rollback_file=filename, puid=1234, pgid=5678)
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "live" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    restore = _RecordingRestore()
    chown = _RecordingChown()
    restore_io = RestoreIO(lock=_FakeLock(), restore=restore)  # type: ignore[arg-type]
    saves = SaveDirectories(tmp_path / "saves")

    # WHEN running the startup restore
    outcome = restore_at_startup(settings, saves, restore_io=restore_io, chown=chown)

    # THEN ownership is re-applied to the saves tree for the game user
    assert outcome is RestoreOutcome.SUCCESS
    assert chown.calls == [((saves.saves_dir,), 1234, 5678)]


def test_restore_for_restart_warns_when_ownership_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a successful scheduled restore whose ownership pass fails
    filename = "enshrouded-20260529-120000.tar.zst"
    settings = _settings(rollback_enabled=True, rollback_file=filename)
    settings = replace(settings, backup_dir=str(tmp_path / "backups"))
    backup_path = tmp_path / "backups" / "live" / filename
    backup_path.parent.mkdir(parents=True)
    backup_path.write_bytes(b"backup")
    restore = _RecordingRestore()
    chown = _RecordingChown(error=OSError("denied"))
    restore_io = RestoreIO(lock=_FakeLock(), restore=restore)  # type: ignore[arg-type]

    # WHEN restoring between stop and relaunch
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.rollback"):
        outcome = restore_for_restart(settings, SaveDirectories(tmp_path / "saves"), restore_io=restore_io, chown=chown)

    # THEN the restore still succeeds with an ownership warning
    assert outcome is RestoreOutcome.SUCCESS
    assert restore.calls == [backup_path]
    assert any("could not set ownership" in record.message for record in caplog.records)
