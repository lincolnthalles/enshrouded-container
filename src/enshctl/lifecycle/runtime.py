"""Server lifecycle state machine and the one ordered exit path."""

import logging
import signal
import subprocess
import threading
from contextlib import suppress
from typing import TYPE_CHECKING

from enshctl import config
from enshctl.backup_protocol import BackupRequest, Trigger
from enshctl.lifecycle.a2s import A2SProbe, UdpA2STransport
from enshctl.lifecycle.autopause import AutoPauseController
from enshctl.lifecycle.control import ControlFiles
from enshctl.lifecycle.io import LifecycleIO, ProcessControl, SystemLifecycleIO, SystemProcessControl
from enshctl.lifecycle.pause_gate import PauseGate
from enshctl.lifecycle.players import PlayerReporter
from enshctl.lifecycle.types import ExitRequest, PauseControl, RestartRequest, ServerProcess
from enshctl.lifecycle.wake import build_wake_source
from enshctl.paths import AUTOPAUSE_DIR
from enshctl.presence import PresenceTracker

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.download.types import ManifestRecord
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
    pause_control: PauseControl | None = None,
    clear_pid: bool = True,
) -> int:
    """Stop the scheduler and server, run the trigger's backup, and clean up once."""
    stop_event.set()
    logger.info("Exiting server lifecycle (%s, code %d)", request.trigger or "startup failure", request.exit_code)
    if pause_control is not None:
        _best_effort(pause_control.stop, "Auto Pause stop")
        _best_effort(pause_control.resume_for_shutdown, "Auto Pause resume")
    stopped = _stop_server(process_handle, settings=settings, process_control=process_control)
    if request.trigger is Trigger.UPDATE and not stopped:
        logger.error("Update restart could not stop the server; skipping backup and cleanup")
        return 1
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
) -> bool:
    if process_handle is None:
        return True
    try:
        if process_handle.poll() is not None:
            return True
        logger.info("Sending SIGINT to server process")
        if not process_control.signal_game(signal.SIGINT):
            with suppress(OSError):
                process_handle.send_signal(signal.SIGINT)
        try:
            process_handle.wait(timeout=settings.shutdown_timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Server did not exit within %ds, sending SIGKILL", settings.shutdown_timeout)
            with suppress(OSError):
                process_control.signal_game(signal.SIGKILL)
            with suppress(OSError):
                process_handle.kill()
            with suppress(OSError):
                process_handle.wait()
    except Exception:
        logger.exception("Failed to stop server process")
        return process_handle.poll() is not None
    return process_handle.poll() is not None


def _run_triggered_backup(trigger: Trigger | None, *, settings: AppSettings, lifecycle_io: LifecycleIO) -> None:
    if trigger is Trigger.SHUTDOWN or trigger is Trigger.UPDATE:
        if not settings.backup_cold:
            return
        wait_seconds = settings.shutdown_backup_wait
        label = "cold update restart" if trigger is Trigger.UPDATE else "cold shutdown"
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
        control_files: ControlFiles | None = None,
        active_manifest: ManifestRecord | None = None,
        shutdown_event: threading.Event | None = None,
    ) -> None:
        self._settings = settings
        self._process_control: ProcessControl = process_control or SystemProcessControl(settings)
        self._lifecycle_io: LifecycleIO = lifecycle_io or SystemLifecycleIO(settings)
        self._control_files = control_files or ControlFiles(
            AUTOPAUSE_DIR,
            puid=settings.puid,
            pgid=settings.pgid,
        )
        self._active_manifest = active_manifest
        self._request: ExitRequest | None = None
        self._stop_event = threading.Event()
        self._shutdown_event = shutdown_event if shutdown_event is not None else threading.Event()
        self._restart_request = RestartRequest()
        self._restart_manifest: ManifestRecord | None = None
        self._restart_requested = False
        self._pause_gate = PauseGate()
        self._shutdown_requested = False
        self._stream_thread: threading.Thread | None = None
        self._log_thread: threading.Thread | None = None
        self._reporter_thread: threading.Thread | None = None
        self._pause_control: AutoPauseController | None = None
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

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    @property
    def restart_manifest(self) -> ManifestRecord | None:
        return self._restart_manifest

    def run(self) -> int:
        """Launch, supervise, and exit the server; return the process exit code."""
        self._install_signal_handlers()
        process_handle: ServerProcess | None = None
        try:
            self._prepare_auto_pause()
            if self._shutdown_event.is_set():
                if self._request is None:
                    self._request = ExitRequest(None, 0)
                return self._finish(None)
            process_handle = self._process_control.start()
            self._lifecycle_io.write_pid(process_handle.pid)
            self._pid_written = True
            if self._request is not None:
                return self._finish(process_handle)
            self._presence = PresenceTracker()
            self._reporter = PlayerReporter(self._presence, self._settings, pause_gate=self._pause_gate)
            self._reporter_thread = self._reporter.start(self._stop_event)
            self._stream_thread = self._process_control.stream(process_handle, on_line=self._reporter.observe)
            if self._settings.auto_pause_enabled:
                self._pause_control = self._build_auto_pause(self._stream_thread, self._presence)
                self._pause_control.start(self._stop_event)
            if self._settings.backup_live:
                self._lifecycle_io.start_scheduler(self._stop_event, pause_gate=self._pause_gate)
            else:
                logger.info("Live backups disabled")
            if self._active_manifest is not None:
                self._lifecycle_io.start_updater(
                    self._presence,
                    active_manifest=self._active_manifest,
                    stop_event=self._stop_event,
                    restart_request=self._restart_request,
                    stream_healthy=self._stream_thread.is_alive,
                    is_paused=self._control_files.is_paused,
                    pause_gate=self._pause_gate,
                )
            if self._settings.log_tail:
                self._log_thread = self._process_control.start_log_tail(self._stop_event)
            self._process_control.start_resource_poller(
                process_handle.pid,
                self._stop_event,
                pause_gate=self._pause_gate,
            )
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

    def _prepare_auto_pause(self) -> None:
        try:
            if not self._process_control.resume_all():
                logger.warning("Auto Pause startup resume could not verify a clean Wine tree")
        except Exception:
            logger.exception("Auto Pause startup resume failed")
        self._control_files.clear_runtime()

    def _build_auto_pause(self, stream_thread: threading.Thread, tracker: PresenceTracker) -> AutoPauseController:
        endpoint = config.generated_query_endpoint()
        saves_dir = config.generated_save_directories(settings=self._settings).saves_dir
        a2s = A2SProbe(UdpA2STransport(endpoint)) if endpoint is not None else None
        wake_source = build_wake_source(endpoint, self._settings.auto_pause_wake_filter)
        return AutoPauseController(
            settings=self._settings,
            tracker=tracker,
            process_control=self._process_control,
            control_files=self._control_files,
            saves_dir=saves_dir,
            query_endpoint=endpoint,
            a2s=a2s,
            wake_source=wake_source,
            pause_gate=self._pause_gate,
            stream_healthy=stream_thread.is_alive,
        )

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, _signum: int, _frame: object) -> None:
        self.request_shutdown()

    def _wait_for_exit(self, process_handle: ServerProcess) -> None:
        while self._request is None:
            if self._shutdown_event.is_set():
                self._record_shutdown(Trigger.SHUTDOWN)
                break
            if self._restart_request.event.is_set():
                self._accept_restart_request()
                if self._request is not None:
                    break
            if process_handle.poll() is not None:
                exit_code = process_handle.wait()
                if not self._shutdown_requested and self._request is None:
                    logger.error("Server exited unexpectedly (code %d)", exit_code)
                    # A signal can land while logging; re-check before recording the crash.
                    if not self._shutdown_requested and self._request is None:
                        self._request = ExitRequest(Trigger.CRASH, exit_code)
                break
            self._shutdown_event.wait(timeout=0.5)

    def _accept_restart_request(self) -> None:
        manifest = self._restart_request.consume()
        if manifest is None:
            logger.error("Auto Update: restart request had no pending Manifest; ignoring")
            return
        self._restart_manifest = manifest
        self._restart_requested = True
        self._request = ExitRequest(Trigger.UPDATE, 0)

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
            pause_control=self._pause_control,
            clear_pid=self._pid_written,
        )
        if request.trigger is Trigger.UPDATE and process_handle is not None and process_handle.poll() is None:
            logger.error("Auto Update: server did not stop; not relaunching")
            self._restart_requested = False
            self._restart_manifest = None
            self._exit_code = 1
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=5)
        if self._log_thread is not None:
            self._log_thread.join(timeout=5)
        if self._reporter_thread is not None:
            self._reporter_thread.join(timeout=5)
        return self._exit_code
