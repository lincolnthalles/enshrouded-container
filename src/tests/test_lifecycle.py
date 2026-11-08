"""Tests for the ordered server lifecycle exit path."""

import signal
import subprocess
import threading
from dataclasses import replace
from typing import IO, TYPE_CHECKING
from unittest.mock import patch

from enshctl.backup_protocol import BackupRequest, Trigger
from enshctl.config import SaveDirectories
from enshctl.download.types import ManifestRecord
from enshctl.lifecycle import runtime
from enshctl.lifecycle.control import AutoPauseStatus, ControlFiles
from enshctl.lifecycle.io import SystemLifecycleIO
from enshctl.lifecycle.pause_gate import PauseGate
from enshctl.lifecycle.runtime import ServerLifecycle, exit_server
from enshctl.lifecycle.types import ExitRequest, RestartRequest, ServerProcess
from enshctl.paths import SAVE_DIR
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest
    from enshctl.presence import PresenceTracker


class FakeProcess:
    pid: int
    stdout: IO[bytes] | None

    def __init__(self, *, returncode: int | None = None, timeouts: int = 0, stuck: bool = False) -> None:
        self.pid = 4321
        self.stdout = None
        self._returncode = returncode
        self._timeouts = timeouts
        self._stuck = stuck
        self.signals: list[int] = []
        self.killed = False
        self.waits: list[float | None] = []
        self.on_wait: Callable[[], None] | None = None

    def poll(self) -> int | None:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        if self.on_wait is not None:
            self.on_wait()
        if self._timeouts > 0:
            self._timeouts -= 1
            command = "server"
            raise subprocess.TimeoutExpired(command, timeout if timeout is not None else 0.0)
        if self._stuck:
            return 0
        if self._returncode is None:
            self._returncode = 0
        return self._returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def kill(self) -> None:
        self.killed = True
        self._returncode = -signal.SIGKILL


class FakeProcessControl:
    def __init__(self, process: FakeProcess, events: list[object]) -> None:
        self.process = process
        self.events = events
        self.started = False
        self.stream_error: Exception | None = None
        self.start_error: Exception | None = None
        self.signal_error: Exception | None = None
        self.on_start: Callable[[], None] | None = None
        self.stream_on_line: Callable[[str], None] | None = None
        self.stream_line: str | None = None
        self.resume_calls = 0
        self.suspend_calls = 0
        self.resource_gate: PauseGate | None = None

    def start(self) -> ServerProcess:
        self.started = True
        self.events.append("start")
        if self.on_start is not None:
            self.on_start()
        if self.start_error is not None:
            raise self.start_error
        return self.process

    def signal_game(self, sig: int) -> bool:
        self.events.append(("signal_game", sig))
        if self.signal_error is not None:
            raise self.signal_error
        return True

    def signal_pid(self, pid: int, sig: int) -> bool:
        del pid, sig
        return True

    def wine_tree(self) -> None:
        return None

    def suspend_all(self) -> bool:
        self.suspend_calls += 1
        return True

    def resume_all(self) -> bool:
        self.resume_calls += 1
        return True

    def stream(
        self,
        process: ServerProcess,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> threading.Thread:
        del process
        self.events.append("stream")
        self.stream_on_line = on_line
        if on_line is not None and self.stream_line is not None:
            on_line(self.stream_line)
        if self.stream_error is not None:
            raise self.stream_error
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread

    def start_log_tail(self, stop_event: threading.Event) -> threading.Thread:
        del stop_event
        self.events.append("log_tail")
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread

    def start_resource_poller(
        self,
        pid: int,
        stop_event: threading.Event,
        *,
        pause_gate: PauseGate,
    ) -> None:
        del pid, stop_event
        self.resource_gate = pause_gate
        self.events.append("resource_poller")


class FakePauseControl:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.stop_error: Exception | None = None
        self.resume_error: Exception | None = None

    def stop(self) -> None:
        self.events.append("pause_stop")
        if self.stop_error is not None:
            raise self.stop_error

    def resume_for_shutdown(self) -> None:
        self.events.append("pause_resume")
        if self.resume_error is not None:
            raise self.resume_error


class FakeAutoPause(FakePauseControl):
    def start(self, stop_event: threading.Event) -> threading.Thread:
        del stop_event
        self.events.append("pause_start")
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread


class FakeLifecycleIO:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.backups: list[BackupRequest] = []
        self.backup_required = True
        self.write_error: Exception | None = None
        self.cleanup_error: Exception | None = None
        self.clear_error: Exception | None = None
        self.scheduler_gate: PauseGate | None = None
        self.restart_request: RestartRequest | None = None
        self.active_manifest: ManifestRecord | None = None
        self.updater_started = threading.Event()

    def backup_needed(self) -> bool:
        return self.backup_required

    def run_backup(self, request: BackupRequest) -> None:
        self.backups.append(request)
        self.events.append(("backup", request))

    def start_scheduler(self, stop_event: threading.Event, *, pause_gate: PauseGate) -> threading.Thread:
        del stop_event
        self.scheduler_gate = pause_gate
        self.events.append("scheduler")
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread

    def start_updater(
        self,
        tracker: PresenceTracker,
        *,
        active_manifest: ManifestRecord,
        stop_event: threading.Event,
        restart_request: RestartRequest,
        stream_healthy: Callable[[], bool],
        is_paused: Callable[[], bool],
        pause_gate: PauseGate,
    ) -> None:
        del tracker, stop_event, stream_healthy, is_paused, pause_gate
        self.active_manifest = active_manifest
        self.restart_request = restart_request
        self.events.append("updater")
        self.updater_started.set()

    def cleanup_wine(self) -> None:
        self.events.append("wine")
        if self.cleanup_error is not None:
            raise self.cleanup_error

    def write_pid(self, pid: int) -> None:
        self.events.append(("write_pid", pid))
        if self.write_error is not None:
            raise self.write_error

    def clear_pid(self) -> None:
        self.events.append("clear_pid")
        if self.clear_error is not None:
            raise self.clear_error


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


def _exit(
    request: ExitRequest,
    process: FakeProcess,
    control: FakeProcessControl,
    io: FakeLifecycleIO,
    settings: AppSettings,
    *,
    pause_control: FakePauseControl | None = None,
) -> int:
    return exit_server(
        request,
        settings=settings,
        process_handle=process,
        stop_event=threading.Event(),
        process_control=control,
        lifecycle_io=io,
        pause_control=pause_control,
    )


def test_pause_control_stops_and_resumes_before_signal() -> None:
    # GIVEN a running server with Auto Pause attached
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    pause = FakePauseControl(events)
    settings = _settings(backup_cold=False, backup_emergency=False)

    # WHEN the shutdown exit path runs
    _exit(ExitRequest(Trigger.SHUTDOWN, 0), process, control, io, settings, pause_control=pause)

    # THEN Auto Pause stops and resumes before SIGINT
    assert events[:3] == ["pause_stop", "pause_resume", ("signal_game", signal.SIGINT)]


def test_pause_control_resumes_without_a_process() -> None:
    # GIVEN Auto Pause attached to an exit with no wrapper process
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    pause = FakePauseControl(events)

    # WHEN the shutdown exit path runs with no process handle
    exit_server(
        ExitRequest(Trigger.SHUTDOWN, 0),
        settings=_settings(backup_cold=False, backup_emergency=False),
        process_handle=None,
        stop_event=threading.Event(),
        process_control=control,
        lifecycle_io=io,
        pause_control=pause,
        clear_pid=False,
    )

    # THEN the tree is resumed even though there is no wrapper
    assert events[:2] == ["pause_stop", "pause_resume"]


def test_pause_control_failure_does_not_block_exit() -> None:
    # GIVEN Auto Pause whose stop and resume both fail
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    pause = FakePauseControl(events)
    pause.stop_error = OSError("stop failed")
    pause.resume_error = OSError("resume failed")

    # WHEN the shutdown exit path runs
    code = _exit(
        ExitRequest(Trigger.SHUTDOWN, 0),
        process,
        control,
        io,
        _settings(backup_cold=False, backup_emergency=False),
        pause_control=pause,
    )

    # THEN the server is still signalled and cleanup runs
    assert code == 0
    assert ("signal_game", signal.SIGINT) in events
    assert events[-1] == "clear_pid"


def test_lifecycle_shared_shutdown_aborts_before_launch() -> None:
    # GIVEN a shared shutdown event set during the update restart window
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    shutdown = threading.Event()
    shutdown.set()

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        code = ServerLifecycle(
            _settings(backup_live=False, backup_cold=False, backup_emergency=False),
            process_control=control,
            lifecycle_io=io,
            save_directories=SaveDirectories(SAVE_DIR),
            shutdown_event=shutdown,
        ).run()

    # THEN it exits cleanly without launching a server
    assert code == 0
    assert "start" not in events
    assert "wine" in events


def test_lifecycle_signal_before_launch_preserves_shutdown_backup() -> None:
    # GIVEN a shutdown signal arriving during pre-launch preparation
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    lifecycle = ServerLifecycle(
        _settings(
            backup_live=False,
            backup_cold=True,
            backup_emergency=False,
            shutdown_backup_wait=5,
        ),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
    )

    # WHEN preparation triggers the shutdown before any server launch
    with (
        patch.object(runtime.signal, "signal"),
        patch.object(lifecycle, "_prepare_auto_pause", side_effect=lifecycle.request_shutdown),
    ):
        code = lifecycle.run()

    # THEN the shutdown trigger survives and the cold backup runs
    assert code == 0
    assert "start" not in events
    assert io.backups == [BackupRequest.for_trigger(Trigger.SHUTDOWN, wait_seconds=5)]
    assert "wine" in events
    assert "clear_pid" not in events


def test_lifecycle_starts_auto_pause_and_resumes_on_exit() -> None:
    # GIVEN a lifecycle with Auto Pause enabled
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    pause = FakeAutoPause(events)
    settings = _settings(auto_pause_enabled=True, backup_live=False, backup_cold=False, backup_emergency=False)

    # WHEN the lifecycle runs
    with (
        patch.object(runtime.signal, "signal"),
        patch.object(runtime.ServerLifecycle, "_build_auto_pause", return_value=pause),
    ):
        code = runtime.ServerLifecycle(
            settings, process_control=control, lifecycle_io=io, save_directories=SaveDirectories(SAVE_DIR)
        ).run()

    # THEN Auto Pause starts after the stream and stops/resumes on exit
    assert code == 0
    assert "pause_start" in events
    assert "pause_stop" in events
    assert "pause_resume" in events


def test_lifecycle_shares_one_pause_gate(tmp_path: Path) -> None:
    # GIVEN a lifecycle with Auto Pause and live backups enabled
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(auto_pause_enabled=True, backup_live=True, backup_cold=False, backup_emergency=False)
    captured: dict[str, object] = {}

    class _CapturedAutoPause(FakeAutoPause):
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            super().__init__(events)

    class _CapturedReporter:
        def __init__(self, tracker: object, settings: object, *, pause_gate: PauseGate) -> None:
            del tracker, settings
            captured["reporter_gate"] = pause_gate

        def start(self, stop_event: threading.Event) -> None:
            del stop_event

        def observe(self, line: str) -> None:
            del line

    # WHEN the lifecycle runs
    with (
        patch.object(runtime.signal, "signal"),
        patch.object(runtime, "AutoPauseController", _CapturedAutoPause),
        patch.object(runtime, "PlayerReporter", _CapturedReporter),
        patch.object(runtime.config, "generated_query_endpoint", return_value=None),
    ):
        code = ServerLifecycle(
            settings,
            process_control=control,
            lifecycle_io=io,
            save_directories=SaveDirectories(tmp_path),
        ).run()

    # THEN the controller, reporter, scheduler, and resource poller share one gate
    gate = captured["pause_gate"]
    assert code == 0
    assert captured["saves_dir"] == tmp_path
    assert isinstance(gate, PauseGate)
    assert captured["reporter_gate"] is gate
    assert control.resource_gate is gate
    assert io.scheduler_gate is gate


def test_system_lifecycle_io_backup_needed_uses_injected_save_dir(tmp_path: Path) -> None:
    # GIVEN a Save directory with a world save and an empty Save directory
    settings = _settings()
    saves = tmp_path / "saves"
    saves.mkdir()
    (saves / "world.ksd").write_bytes(b"save")
    io = SystemLifecycleIO(settings=settings, save_directories=SaveDirectories(saves))

    # WHEN checking whether a backup is needed
    has_saves = io.backup_needed()
    (saves / "world.ksd").unlink()
    is_empty = io.backup_needed()

    # THEN the injected Save directory is used without re-reading the Generated config
    assert has_saves is True
    assert is_empty is False


def test_system_lifecycle_io_forwards_save_dir_to_backup(tmp_path: Path) -> None:
    # GIVEN a lifecycle IO bound to an explicit Save directory
    settings = _settings()
    saves = tmp_path / "saves"
    io = SystemLifecycleIO(settings=settings, save_directories=SaveDirectories(saves))
    request = BackupRequest()

    # WHEN running a backup
    with patch("enshctl.lifecycle.io.backup.run_backup") as mock_run:
        io.run_backup(request)

    # THEN the resolved Save directory crosses the subprocess seam
    mock_run.assert_called_once_with(request, saves_dir=saves)


def test_system_lifecycle_io_forwards_save_dir_to_scheduler(tmp_path: Path) -> None:
    # GIVEN a lifecycle IO bound to an explicit Save directory
    settings = _settings()
    saves = tmp_path / "saves"
    io = SystemLifecycleIO(settings=settings, save_directories=SaveDirectories(saves))
    stop = threading.Event()
    gate = PauseGate()

    # WHEN starting the scheduler
    with patch("enshctl.lifecycle.io.backup.start_scheduler") as mock_start:
        io.start_scheduler(stop, pause_gate=gate)

    # THEN the resolved Save directory crosses to scheduled backups
    mock_start.assert_called_once_with(
        settings.backup_cron,
        stop,
        pause_gate=gate,
        saves_dir=saves,
    )


def test_lifecycle_startup_clears_transient_auto_pause_state(tmp_path: Path) -> None:
    # GIVEN leftover runtime state and an enabled marker
    control_files = ControlFiles(root=tmp_path, puid=0, pgid=0)
    control_files.set_disabled()
    control_files.set_paused()
    control_files.write_status(AutoPauseStatus(state="paused", updated_at=1.0, controller_pid=1))
    control_files.write_request("resume", "token", now=1.0)

    events: list[object] = []
    process = FakeProcess(returncode=0)
    process_control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)

    # WHEN the lifecycle starts
    with patch.object(runtime.signal, "signal"):
        runtime.ServerLifecycle(
            _settings(backup_live=False, backup_cold=False, backup_emergency=False),
            process_control=process_control,
            lifecycle_io=io,
            save_directories=SaveDirectories(SAVE_DIR),
            control_files=control_files,
        ).run()

    # THEN transient state is cleared, the tree is resumed, and disabled survives
    assert process_control.resume_calls >= 1
    assert control_files.is_disabled() is True
    assert control_files.is_paused() is False
    assert control_files.status_path.exists() is False
    assert control_files.request_path.exists() is False


def test_shutdown_exit_orders_server_backup_wine_pid() -> None:
    # GIVEN a running server and save data present
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(shutdown_timeout=7, shutdown_backup_wait=5, backup_cold=True, backup_emergency=False)

    # WHEN the shutdown exit path runs
    code = _exit(ExitRequest(Trigger.SHUTDOWN, 0), process, control, io, settings)

    # THEN the server is signalled, the cold backup runs, then Wine cleanup and PID clear
    assert code == 0
    assert events == [
        ("signal_game", signal.SIGINT),
        ("backup", BackupRequest.for_trigger(Trigger.SHUTDOWN, wait_seconds=5)),
        "wine",
        "clear_pid",
    ]
    assert process.waits == [7]


def test_update_exit_orders_server_cold_backup_wine_pid() -> None:
    # GIVEN a running server and save data present
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(shutdown_timeout=7, shutdown_backup_wait=5, backup_cold=True, backup_emergency=False)

    # WHEN the update restart exit path runs
    code = _exit(ExitRequest(Trigger.UPDATE, 0), process, control, io, settings)

    # THEN the server is signalled, the cold backup runs, then Wine cleanup and PID clear
    assert code == 0
    assert events == [
        ("signal_game", signal.SIGINT),
        ("backup", BackupRequest.for_trigger(Trigger.UPDATE, wait_seconds=5)),
        "wine",
        "clear_pid",
    ]
    assert process.waits == [7]


def test_lifecycle_update_restart_uses_pending_manifest() -> None:
    # GIVEN a lifecycle with an active Manifest and a pending update target
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    active = ManifestRecord("111", "05/29/2026 12:00:00")
    target = ManifestRecord("222", "05/29/2026 13:00:00")
    lifecycle = ServerLifecycle(
        _settings(backup_live=False, backup_cold=False, backup_emergency=False),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
        active_manifest=active,
    )
    codes: list[int] = []

    # WHEN the update controller requests a restart while the lifecycle waits
    with patch.object(runtime.signal, "signal"):
        thread = threading.Thread(target=lambda: codes.append(lifecycle.run()))
        thread.start()
        assert io.updater_started.wait(timeout=1)
        assert io.active_manifest == active
        assert io.restart_request is not None
        io.restart_request.request(target)
        thread.join(timeout=2)

    # THEN the lifecycle exits with the update trigger and exposes the target
    assert not thread.is_alive()
    assert codes == [0]
    assert lifecycle.restart_requested is True
    assert lifecycle.restart_manifest == target
    assert "updater" in events


def test_lifecycle_update_restart_stop_failure_exits_without_relaunch() -> None:
    # GIVEN a server process that ignores the stop wait
    events: list[object] = []
    process = FakeProcess(stuck=True)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    lifecycle = ServerLifecycle(
        _settings(backup_live=False, backup_cold=False, backup_emergency=False),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
        active_manifest=ManifestRecord("111", "05/29/2026 12:00:00"),
    )
    codes: list[int] = []

    # WHEN an update restart is requested but the server remains alive
    with patch.object(runtime.signal, "signal"):
        thread = threading.Thread(target=lambda: codes.append(lifecycle.run()))
        thread.start()
        assert io.updater_started.wait(timeout=1)
        assert io.restart_request is not None
        io.restart_request.request(ManifestRecord("222", "05/29/2026 13:00:00"))
        thread.join(timeout=2)

    # THEN the lifecycle exits non-zero and does not expose a relaunch target
    assert not thread.is_alive()
    assert codes == [1]
    assert lifecycle.restart_requested is False
    assert lifecycle.restart_manifest is None
    assert "wine" not in events
    assert "clear_pid" not in events


def test_crash_exit_skips_signal_and_uses_emergency() -> None:
    # GIVEN a server that already exited with code 9
    events: list[object] = []
    process = FakeProcess(returncode=9)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(backup_cold=False, backup_emergency=True)

    # WHEN the crash exit path runs
    code = _exit(ExitRequest(Trigger.CRASH, 9), process, control, io, settings)

    # THEN no second signal is sent and the emergency backup runs before cleanup
    assert code == 9
    assert events == [
        ("backup", BackupRequest.for_trigger(Trigger.CRASH)),
        "wine",
        "clear_pid",
    ]


def test_force_kill_after_timeout() -> None:
    # GIVEN a server that ignores SIGINT past the grace period
    events: list[object] = []
    process = FakeProcess(timeouts=1)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(shutdown_timeout=1, backup_cold=False, backup_emergency=False)

    # WHEN the shutdown exit path runs
    code = _exit(ExitRequest(Trigger.SHUTDOWN, 0), process, control, io, settings)

    # THEN SIGKILL follows the timeout and cleanup still runs
    assert code == 0
    assert process.killed is True
    assert events == [
        ("signal_game", signal.SIGINT),
        ("signal_game", signal.SIGKILL),
        "wine",
        "clear_pid",
    ]


def test_exit_sets_stop_event() -> None:
    # GIVEN a stop event that is not set
    stop = threading.Event()
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, [])
    io = FakeLifecycleIO([])

    # WHEN the exit path runs
    exit_server(
        ExitRequest(Trigger.SHUTDOWN, 0),
        settings=_settings(backup_cold=False, backup_emergency=False),
        process_handle=process,
        stop_event=stop,
        process_control=control,
        lifecycle_io=io,
    )

    # THEN the scheduler is signalled to stop
    assert stop.is_set()


def test_cleanup_failure_still_clears_pid() -> None:
    # GIVEN a Wine cleanup that fails
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    io.cleanup_error = OSError("wine failed")

    # WHEN the exit path runs
    code = _exit(
        ExitRequest(Trigger.SHUTDOWN, 0),
        process,
        control,
        io,
        _settings(backup_cold=False, backup_emergency=False),
    )

    # THEN the PID file is still cleared and the exit code is preserved
    assert code == 0
    assert events[-1] == "clear_pid"


def test_clear_pid_failure_does_not_escape() -> None:
    # GIVEN a PID clear that fails
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    io.clear_error = OSError("pid failed")

    # WHEN the exit path runs
    code = _exit(
        ExitRequest(Trigger.SHUTDOWN, 0),
        process,
        control,
        io,
        _settings(backup_cold=False, backup_emergency=False),
    )

    # THEN the failure is logged and the exit code is returned
    assert code == 0


def test_stop_failure_still_clears_pid() -> None:
    # GIVEN a server signal that fails
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    control.signal_error = OSError("signal failed")
    io = FakeLifecycleIO(events)

    # WHEN the exit path runs
    code = _exit(
        ExitRequest(Trigger.SHUTDOWN, 0),
        process,
        control,
        io,
        _settings(backup_cold=False, backup_emergency=False),
    )

    # THEN the failure is logged and cleanup still runs
    assert code == 0
    assert events[-1] == "clear_pid"


def test_no_backup_when_trigger_disabled() -> None:
    # GIVEN cold backups disabled
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)

    # WHEN the shutdown exit path runs
    _exit(
        ExitRequest(Trigger.SHUTDOWN, 0),
        process,
        control,
        io,
        _settings(backup_cold=False, backup_emergency=False),
    )

    # THEN no backup is requested
    assert io.backups == []


def test_no_backup_when_saves_absent() -> None:
    # GIVEN cold backups enabled but no save data present
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    io.backup_required = False

    # WHEN the shutdown exit path runs
    _exit(
        ExitRequest(Trigger.SHUTDOWN, 0),
        process,
        control,
        io,
        _settings(backup_cold=True, backup_emergency=False),
    )

    # THEN no backup is requested
    assert io.backups == []


def test_run_returns_crash_code() -> None:
    # GIVEN a server that exits unexpectedly with code 9
    events: list[object] = []
    process = FakeProcess(returncode=9)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(backup_live=False, backup_cold=False, backup_emergency=True)

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        code = ServerLifecycle(
            settings, process_control=control, lifecycle_io=io, save_directories=SaveDirectories(SAVE_DIR)
        ).run()

    # THEN the server code is returned after the emergency backup and cleanup
    assert code == 9
    assert io.backups == [BackupRequest.for_trigger(Trigger.CRASH)]
    assert ("write_pid", process.pid) in events
    assert events[-1] == "clear_pid"


def test_run_starts_scheduler_when_live_enabled() -> None:
    # GIVEN live backups enabled
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(backup_live=True, backup_cold=False, backup_emergency=False)

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        ServerLifecycle(
            settings, process_control=control, lifecycle_io=io, save_directories=SaveDirectories(SAVE_DIR)
        ).run()

    # THEN the scheduler starts
    assert "scheduler" in events


def test_run_skips_scheduler_when_live_disabled() -> None:
    # GIVEN live backups disabled
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    settings = _settings(backup_live=False, backup_cold=False, backup_emergency=False)

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        ServerLifecycle(
            settings, process_control=control, lifecycle_io=io, save_directories=SaveDirectories(SAVE_DIR)
        ).run()

    # THEN no scheduler starts
    assert "scheduler" not in events


def test_run_wires_player_hook_and_logs_join(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a lifecycle with roster output enabled and no summary interval
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    control.stream_line = "[I 00:00:01,000] [session] Remote player added. Player handle: 0(0)"
    io = FakeLifecycleIO(events)
    settings = _settings(
        backup_live=False,
        backup_cold=False,
        backup_emergency=False,
        player_log=True,
        player_poll_interval=0,
    )

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"), caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        code = ServerLifecycle(
            settings, process_control=control, lifecycle_io=io, save_directories=SaveDirectories(SAVE_DIR)
        ).run()

    # THEN the stream receives the presence hook and the join is reported
    assert code == 0
    assert control.stream_on_line is not None
    assert "Player joined: 0(0)" in caplog.text


def test_run_suppresses_player_lines_when_output_disabled(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN roster output disabled
    events: list[object] = []
    process = FakeProcess(returncode=0)
    control = FakeProcessControl(process, events)
    control.stream_line = "[I 00:00:01,000] [session] Remote player added. Player handle: 0(0)"
    io = FakeLifecycleIO(events)
    settings = _settings(
        backup_live=False,
        backup_cold=False,
        backup_emergency=False,
        player_log=False,
        player_poll_interval=60,
    )

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"), caplog.at_level("INFO", logger="enshctl.lifecycle.players"):
        code = ServerLifecycle(
            settings, process_control=control, lifecycle_io=io, save_directories=SaveDirectories(SAVE_DIR)
        ).run()

    # THEN the hook still runs but no roster line is emitted
    assert code == 0
    assert control.stream_on_line is not None
    assert "Player joined" not in caplog.text


def test_run_shutdown_before_start_skips_launch() -> None:
    # GIVEN a shutdown request recorded before the server starts
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    lifecycle = ServerLifecycle(
        _settings(backup_cold=False, backup_emergency=False),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
    )
    lifecycle.request_shutdown()

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        code = lifecycle.run()

    # THEN it exits cleanly without launching the server or clearing another owner's PID
    assert code == 0
    assert control.started is False
    assert events == ["wine"]


def test_signal_handler_records_without_side_effects() -> None:
    # GIVEN a lifecycle whose signal handler is captured at installation
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    handlers: dict[int, object] = {}

    def _install(signum: int, handler: object) -> None:
        handlers[signum] = handler

    def _signal_during_start() -> None:
        handler = handlers[signal.SIGTERM]
        assert callable(handler)
        handler(signal.SIGTERM, None)
        handler(signal.SIGTERM, None)
        assert events == ["start"]

    control.on_start = _signal_during_start
    lifecycle = ServerLifecycle(
        _settings(backup_cold=False, backup_emergency=False),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
    )

    # WHEN SIGTERM arrives while the server is starting
    with patch.object(runtime.signal, "signal", side_effect=_install):
        code = lifecycle.run()

    # THEN the handler only recorded the request; the main thread ran the exit
    assert code == 0
    assert ("write_pid", process.pid) in events
    assert "scheduler" not in events
    assert events[-1] == "clear_pid"


def test_repeated_shutdown_request_is_ignored() -> None:
    # GIVEN a shutdown already requested
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    lifecycle = ServerLifecycle(
        _settings(backup_cold=False, backup_emergency=False),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
    )

    # WHEN a second request arrives
    lifecycle.request_shutdown()
    lifecycle.request_shutdown()

    # THEN only one exit path runs and no PID is cleared because none was written
    with patch.object(runtime.signal, "signal"):
        code = lifecycle.run()
    assert code == 0
    assert control.started is False
    assert events == ["wine"]


def test_run_cleans_up_when_pid_write_fails() -> None:
    # GIVEN a PID write that fails after the server starts
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    io.write_error = OSError("pid failed")

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        code = ServerLifecycle(
            _settings(backup_cold=False, backup_emergency=False),
            process_control=control,
            lifecycle_io=io,
            save_directories=SaveDirectories(SAVE_DIR),
        ).run()

    # THEN the server is stopped and Wine cleanup still runs without clearing another owner's marker
    assert code == 1
    assert process.killed is False
    assert events[-1] == "wine"
    assert "clear_pid" not in events


def test_run_cleans_up_when_streaming_fails() -> None:
    # GIVEN output streaming that fails after the PID is written
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    control.stream_error = OSError("stream failed")
    io = FakeLifecycleIO(events)

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        code = ServerLifecycle(
            _settings(backup_cold=False, backup_emergency=False),
            process_control=control,
            lifecycle_io=io,
            save_directories=SaveDirectories(SAVE_DIR),
        ).run()

    # THEN the server is stopped and cleanup still runs
    assert code == 1
    assert events[-1] == "clear_pid"


def test_run_launch_failure_skips_backup() -> None:
    # GIVEN a server launch that fails before any process exists
    events: list[object] = []
    process = FakeProcess()
    control = FakeProcessControl(process, events)
    control.start_error = OSError("launch failed")
    io = FakeLifecycleIO(events)

    # WHEN the lifecycle runs
    with patch.object(runtime.signal, "signal"):
        code = ServerLifecycle(
            _settings(backup_cold=False, backup_emergency=True),
            process_control=control,
            lifecycle_io=io,
            save_directories=SaveDirectories(SAVE_DIR),
        ).run()

    # THEN it exits 1 with Wine cleanup but no PID clear or emergency backup
    assert code == 1
    assert io.backups == []
    assert events == ["start", "wine"]


def test_shutdown_signal_during_exit_preserves_request() -> None:
    # GIVEN a server that exits while a shutdown signal arrives
    events: list[object] = []
    process = FakeProcess(returncode=9)
    control = FakeProcessControl(process, events)
    io = FakeLifecycleIO(events)
    lifecycle = ServerLifecycle(
        _settings(backup_cold=False, backup_emergency=True),
        process_control=control,
        lifecycle_io=io,
        save_directories=SaveDirectories(SAVE_DIR),
    )
    process.on_wait = lifecycle.request_shutdown

    # WHEN the lifecycle observes the exit
    with patch.object(runtime.signal, "signal"):
        code = lifecycle.run()

    # THEN the shutdown request wins over the crash path
    assert code == 0
    assert io.backups == []
    assert events[-1] == "clear_pid"
