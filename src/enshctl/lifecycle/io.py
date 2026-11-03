"""Lifecycle seams and their production adapters."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from enshctl import config, resources
from enshctl.backup.core import backup_needed as backup_is_needed
from enshctl.lifecycle import backup, process as process_module
from enshctl.pidfile import PidFile

if TYPE_CHECKING:
    import threading

    from enshctl.backup_protocol import BackupRequest
    from enshctl.lifecycle.types import ServerProcess
    from enshctl.settings import AppSettings


class ProcessControl(Protocol):
    """Process, signal, stream, and background-thread operations."""

    def start(self) -> ServerProcess: ...

    def signal(self, sig: int) -> bool: ...

    def stream(self, process: ServerProcess) -> threading.Thread: ...

    def start_log_tail(self, stop_event: threading.Event) -> threading.Thread: ...

    def start_resource_poller(self, pid: int, stop_event: threading.Event) -> threading.Thread | None: ...


class LifecycleIO(Protocol):
    """Backup, Wine, and PID side effects of one lifecycle exit."""

    def backup_needed(self) -> bool: ...

    def run_backup(self, request: BackupRequest) -> None: ...

    def start_scheduler(self, stop_event: threading.Event) -> threading.Thread: ...

    def cleanup_wine(self) -> None: ...

    def write_pid(self, pid: int) -> None: ...

    def clear_pid(self) -> None: ...


@dataclass(frozen=True)
class SystemProcessControl:
    """Production process adapter — Wine, signals, streams, and background threads."""

    settings: AppSettings

    def start(self) -> ServerProcess:
        return process_module.start_server(self.settings)

    def signal(self, sig: int) -> bool:
        return process_module.signal_game(sig)

    def stream(self, process: ServerProcess) -> threading.Thread:
        return process_module.stream_output(process)

    def start_log_tail(self, stop_event: threading.Event) -> threading.Thread:
        return process_module.start_log_tail_thread(stop_event)

    def start_resource_poller(self, pid: int, stop_event: threading.Event) -> threading.Thread | None:
        return resources.start_resource_poller(pid, stop_event, interval=self.settings.resource_poll_interval)


@dataclass(frozen=True)
class SystemLifecycleIO:
    """Production side-effect adapter — backup spawning, Wine cleanup, and the PID file."""

    settings: AppSettings
    pid_file: PidFile = field(default_factory=PidFile)

    def backup_needed(self) -> bool:
        saves_dir = config.generated_save_directories(settings=self.settings).saves_dir
        return backup_is_needed(saves_dir)

    def run_backup(self, request: BackupRequest) -> None:
        backup.run_backup(request)

    def start_scheduler(self, stop_event: threading.Event) -> threading.Thread:
        return backup.start_scheduler(self.settings.backup_cron, stop_event)

    def cleanup_wine(self) -> None:
        process_module.cleanup_wineserver(self.settings)

    def write_pid(self, pid: int) -> None:
        self.pid_file.write(pid)

    def clear_pid(self) -> None:
        self.pid_file.clear()
