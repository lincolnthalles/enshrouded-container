"""Tests for the ordered server lifecycle exit path."""

import signal
import subprocess
import threading
from dataclasses import replace
from typing import IO, TYPE_CHECKING
from unittest.mock import patch

from enshctl.backup_protocol import BackupRequest, Trigger
from enshctl.lifecycle import runtime
from enshctl.lifecycle.runtime import ServerLifecycle, exit_server
from enshctl.lifecycle.types import ExitRequest, ServerProcess
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable


class FakeProcess:
    pid: int
    stdout: IO[bytes] | None

    def __init__(self, *, returncode: int | None = None, timeouts: int = 0) -> None:
        self.pid = 4321
        self.stdout = None
        self._returncode = returncode
        self._timeouts = timeouts
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

    def start(self) -> ServerProcess:
        self.started = True
        self.events.append("start")
        if self.on_start is not None:
            self.on_start()
        if self.start_error is not None:
            raise self.start_error
        return self.process

    def signal(self, sig: int) -> bool:
        self.events.append(("signal", sig))
        if self.signal_error is not None:
            raise self.signal_error
        return True

    def stream(self, process: ServerProcess) -> threading.Thread:
        del process
        self.events.append("stream")
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

    def start_resource_poller(self, pid: int, stop_event: threading.Event) -> None:
        del pid, stop_event
        self.events.append("resource_poller")


class FakeLifecycleIO:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.backups: list[BackupRequest] = []
        self.backup_required = True
        self.write_error: Exception | None = None
        self.cleanup_error: Exception | None = None
        self.clear_error: Exception | None = None

    def backup_needed(self) -> bool:
        return self.backup_required

    def run_backup(self, request: BackupRequest) -> None:
        self.backups.append(request)
        self.events.append(("backup", request))

    def start_scheduler(self, stop_event: threading.Event) -> threading.Thread:
        del stop_event
        self.events.append("scheduler")
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread

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
) -> int:
    return exit_server(
        request,
        settings=settings,
        process_handle=process,
        stop_event=threading.Event(),
        process_control=control,
        lifecycle_io=io,
    )


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
        ("signal", signal.SIGINT),
        ("backup", BackupRequest.for_trigger(Trigger.SHUTDOWN, wait_seconds=5)),
        "wine",
        "clear_pid",
    ]
    assert process.waits == [7]


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
    assert events == [("signal", signal.SIGINT), ("signal", signal.SIGKILL), "wine", "clear_pid"]


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
        code = ServerLifecycle(settings, process_control=control, lifecycle_io=io).run()

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
        ServerLifecycle(settings, process_control=control, lifecycle_io=io).run()

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
        ServerLifecycle(settings, process_control=control, lifecycle_io=io).run()

    # THEN no scheduler starts
    assert "scheduler" not in events


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
    )
    process.on_wait = lifecycle.request_shutdown

    # WHEN the lifecycle observes the exit
    with patch.object(runtime.signal, "signal"):
        code = lifecycle.run()

    # THEN the shutdown request wins over the crash path
    assert code == 0
    assert io.backups == []
    assert events[-1] == "clear_pid"
