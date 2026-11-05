"""Server lifecycle state machine and the one ordered exit path."""

import logging
import signal
import subprocess
import threading
from contextlib import suppress
from typing import TYPE_CHECKING

from enshctl.backup_protocol import BackupRequest, Trigger
from enshctl.lifecycle.io import LifecycleIO, ProcessControl, SystemLifecycleIO, SystemProcessControl
from enshctl.lifecycle.players import PlayerReporter
from enshctl.lifecycle.types import ExitRequest, ServerProcess
from enshctl.presence import PresenceTracker

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


def exit_server(
    request: ExitRequest,
    *,
    settings: AppSettings,
    process_handle: ServerProcess | None,
    stop_event: threading.Event,
    process_control: ProcessControl,
    lifecycle_io: LifecycleIO,
    clear_pid: bool = True,
) -> int:
    """Stop the scheduler and server, run the trigger's backup, and clean up once."""
    stop_event.set()
    logger.info("Exiting server lifecycle (%s, code %d)", request.trigger or "startup failure", request.exit_code)
    _stop_server(process_handle, settings=settings, process_control=process_control)
    _run_triggered_backup(request.trigger, settings=settings, lifecycle_io=lifecycle_io)
    _best_effort(lifecycle_io.cleanup_wine, "Wine cleanup")
    if clear_pid:
        _best_effort(lifecycle_io.clear_pid, "PID file cleanup")
    logger.info("Server lifecycle ended with code %d", request.exit_code)
    return request.exit_code


def _stop_server(
    process_handle: ServerProcess | None,
    *,
    settings: AppSettings,
    process_control: ProcessControl,
) -> None:
    if process_handle is None:
        return
    try:
        if process_handle.poll() is not None:
            return
        logger.info("Sending SIGINT to server process")
        if not process_control.signal(signal.SIGINT):
            with suppress(OSError):
                process_handle.send_signal(signal.SIGINT)
        try:
            process_handle.wait(timeout=settings.shutdown_timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Server did not exit within %ds, sending SIGKILL", settings.shutdown_timeout)
            with suppress(OSError):
                process_control.signal(signal.SIGKILL)
            with suppress(OSError):
                process_handle.kill()
            with suppress(OSError):
                process_handle.wait()
    except Exception:
        logger.exception("Failed to stop server process")


def _run_triggered_backup(trigger: Trigger | None, *, settings: AppSettings, lifecycle_io: LifecycleIO) -> None:
    if trigger is Trigger.SHUTDOWN:
        if not settings.backup_cold:
            return
        wait_seconds = settings.shutdown_backup_wait
        label = "cold shutdown"
    elif trigger is Trigger.CRASH:
        if not settings.backup_emergency:
            return
        wait_seconds = 0
        label = "emergency"
    else:
        return
    try:
        if not lifecycle_io.backup_needed():
            return
        logger.info("Creating %s backup", label)
        lifecycle_io.run_backup(BackupRequest.for_trigger(trigger, wait_seconds=wait_seconds))
    except Exception:
        logger.exception("Failed to run %s backup", label)


def _best_effort(action: Callable[[], None], description: str) -> None:
    try:
        action()
    except Exception:
        logger.exception("%s failed", description)


class ServerLifecycle:
    """Run one server process from launch through a single ordered exit."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        process_control: ProcessControl | None = None,
        lifecycle_io: LifecycleIO | None = None,
    ) -> None:
        self._settings = settings
        self._process_control: ProcessControl = process_control or SystemProcessControl(settings)
        self._lifecycle_io: LifecycleIO = lifecycle_io or SystemLifecycleIO(settings)
        self._request: ExitRequest | None = None
        self._stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._shutdown_requested = False
        self._stream_thread: threading.Thread | None = None
        self._log_thread: threading.Thread | None = None
        self._reporter_thread: threading.Thread | None = None
        self._presence: PresenceTracker | None = None
        self._reporter: PlayerReporter | None = None
        self._pid_written = False
        self._finished = False
        self._exit_code = 1

    def request_shutdown(self, trigger: Trigger = Trigger.SHUTDOWN) -> None:
        """Record a shutdown request and wake the main loop."""
        self._shutdown_requested = True
        self._record_shutdown(trigger)
        self._stop_event.set()
        self._shutdown_event.set()

    def _record_shutdown(self, trigger: Trigger) -> None:
        if self._request is None:
            self._request = ExitRequest(trigger, 0)

    def run(self) -> int:
        """Launch, supervise, and exit the server; return the process exit code."""
        self._install_signal_handlers()
        process_handle: ServerProcess | None = None
        try:
            if self._request is not None:
                return self._finish(None)
            process_handle = self._process_control.start()
            self._lifecycle_io.write_pid(process_handle.pid)
            self._pid_written = True
            if self._request is not None:
                return self._finish(process_handle)
            self._presence = PresenceTracker()
            self._reporter = PlayerReporter(self._presence, self._settings)
            self._reporter_thread = self._reporter.start(self._stop_event)
            self._stream_thread = self._process_control.stream(process_handle, on_line=self._reporter.observe)
            if self._settings.backup_live:
                self._lifecycle_io.start_scheduler(self._stop_event)
            else:
                logger.info("Live backups disabled")
            if self._settings.log_tail:
                self._log_thread = self._process_control.start_log_tail(self._stop_event)
            self._process_control.start_resource_poller(process_handle.pid, self._stop_event)
            self._wait_for_exit(process_handle)
        except Exception:
            logger.exception("Server lifecycle failed")
            self._request = self._request or ExitRequest(
                Trigger.CRASH if process_handle is not None else None,
                1,
            )
            self._finish(process_handle)
            return self._exit_code
        return self._finish(process_handle)

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, _signum: int, _frame: object) -> None:
        self.request_shutdown()

    def _wait_for_exit(self, process_handle: ServerProcess) -> None:
        while self._request is None:
            if process_handle.poll() is not None:
                exit_code = process_handle.wait()
                if not self._shutdown_requested and self._request is None:
                    logger.error("Server exited unexpectedly (code %d)", exit_code)
                    # A signal can land while logging; re-check before recording the crash.
                    if not self._shutdown_requested and self._request is None:
                        self._request = ExitRequest(Trigger.CRASH, exit_code)
                break
            self._shutdown_event.wait(timeout=0.5)

    def _finish(self, process_handle: ServerProcess | None) -> int:
        if self._finished:
            return self._exit_code
        self._finished = True
        request = self._request or ExitRequest(Trigger.CRASH, 1)
        self._exit_code = exit_server(
            request,
            settings=self._settings,
            process_handle=process_handle,
            stop_event=self._stop_event,
            process_control=self._process_control,
            lifecycle_io=self._lifecycle_io,
            clear_pid=self._pid_written,
        )
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=5)
        if self._log_thread is not None:
            self._log_thread.join(timeout=5)
        if self._reporter_thread is not None:
            self._reporter_thread.join(timeout=5)
        return self._exit_code
