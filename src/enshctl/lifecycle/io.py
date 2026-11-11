"""Lifecycle seams and their production adapters."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from enshctl import resources
from enshctl.backup.core import backup_needed as backup_is_needed
from enshctl.download import flow as download_flow
from enshctl.lifecycle import backup, gamelog, server, wine
from enshctl.lifecycle.auto_update import AutoUpdateController, is_auto_update_active
from enshctl.lifecycle.rollback import RollbackController, is_rollback_scheduled
from enshctl.manifests import latest_manifest, record_latest_manifest
from enshctl.pidfile import PidFile

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from enshctl.backup_protocol import BackupRequest
    from enshctl.config import SaveDirectories
    from enshctl.download.types import ManifestRecord
    from enshctl.lifecycle.pause_gate import PauseGate
    from enshctl.lifecycle.server import WineTree
    from enshctl.lifecycle.types import RestartRequest, ServerProcess
    from enshctl.presence import PresenceGate
    from enshctl.settings import AppSettings


class ProcessControl(Protocol):
    """Process, signal, stream, and background-thread operations."""

    def start(self) -> ServerProcess: ...

    def signal_game(self, sig: int) -> bool: ...

    def signal_pid(self, pid: int, sig: int) -> bool: ...

    def wine_tree(self) -> WineTree | None: ...

    def suspend_all(self) -> bool: ...

    def resume_all(self) -> bool: ...

    def stream(
        self,
        process: ServerProcess,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> threading.Thread: ...

    def start_log_tail(self, stop_event: threading.Event) -> threading.Thread: ...

    def start_resource_poller(
        self,
        pid: int,
        stop_event: threading.Event,
        *,
        pause_gate: PauseGate,
    ) -> threading.Thread | None: ...


class LifecycleIO(Protocol):
    """Backup, Wine, and PID side effects of one lifecycle exit."""

    def backup_needed(self) -> bool: ...

    def run_backup(self, request: BackupRequest) -> None: ...

    def start_scheduler(self, stop_event: threading.Event, *, pause_gate: PauseGate) -> threading.Thread: ...

    def start_updater(
        self,
        presence_gate: PresenceGate,
        *,
        active_manifest: ManifestRecord,
        stop_event: threading.Event,
        restart_request: RestartRequest,
        is_paused: Callable[[], bool],
        pause_gate: PauseGate,
    ) -> threading.Thread | None: ...

    def start_rollback(
        self,
        rollback_request: threading.Event,
        stop_event: threading.Event,
    ) -> threading.Thread | None: ...

    def cleanup_wine(self) -> None: ...

    def write_pid(self, pid: int) -> None: ...

    def clear_pid(self) -> None: ...


@dataclass(frozen=True)
class SystemProcessControl:
    """Production process adapter — Wine, signals, streams, and background threads."""

    settings: AppSettings

    def start(self) -> ServerProcess:
        return server.start(self.settings)

    def signal_game(self, sig: int) -> bool:
        return server.signal_game(sig)

    def signal_pid(self, pid: int, sig: int) -> bool:
        return server.signal_pid(pid, sig)

    def wine_tree(self) -> WineTree | None:
        return server.wine_tree()

    def suspend_all(self) -> bool:
        return server.suspend_all()

    def resume_all(self) -> bool:
        return server.resume_all()

    def stream(
        self,
        process: ServerProcess,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> threading.Thread:
        return server.stream(process, on_line=on_line)

    def start_log_tail(self, stop_event: threading.Event) -> threading.Thread:
        return gamelog.start_tail(stop_event)

    def start_resource_poller(
        self,
        pid: int,
        stop_event: threading.Event,
        *,
        pause_gate: PauseGate,
    ) -> threading.Thread | None:
        return resources.start_resource_poller(
            pid,
            stop_event,
            pause_gate=pause_gate,
            interval=self.settings.resource_poll_interval,
        )


@dataclass(frozen=True)
class SystemLifecycleIO:
    """Production side-effect adapter — backup spawning, Wine cleanup, and the PID file."""

    settings: AppSettings
    save_directories: SaveDirectories
    pid_file: PidFile = field(default_factory=PidFile)

    def backup_needed(self) -> bool:
        return backup_is_needed(self.save_directories.saves_dir)

    def run_backup(self, request: BackupRequest) -> None:
        backup.run_backup(request, saves_dir=self.save_directories.saves_dir)

    def start_scheduler(self, stop_event: threading.Event, *, pause_gate: PauseGate) -> threading.Thread:
        return backup.start_scheduler(
            self.settings.backup_cron,
            stop_event,
            pause_gate=pause_gate,
            saves_dir=self.save_directories.saves_dir,
        )

    def start_updater(
        self,
        presence_gate: PresenceGate,
        *,
        active_manifest: ManifestRecord,
        stop_event: threading.Event,
        restart_request: RestartRequest,
        is_paused: Callable[[], bool],
        pause_gate: PauseGate,
    ) -> threading.Thread | None:
        if not is_auto_update_active(self.settings):
            return None
        controller = AutoUpdateController(
            settings=self.settings,
            active_manifest=active_manifest,
            presence_gate=presence_gate,
            pause_gate=pause_gate,
            list_latest=latest_manifest,
            download=self._download_manifest,
            restart_request=restart_request,
            is_paused=is_paused,
        )
        return controller.start(stop_event)

    def _download_manifest(self, manifest: ManifestRecord) -> None:
        download_flow.download_version(manifest.manifest_id, self.settings, version_spec="latest")
        record_latest_manifest(manifest.manifest_id, manifest.timestamp)

    def start_rollback(
        self,
        rollback_request: threading.Event,
        stop_event: threading.Event,
    ) -> threading.Thread | None:
        if not is_rollback_scheduled(self.settings):
            return None
        return RollbackController(settings=self.settings, rollback_request=rollback_request).start(stop_event)

    def cleanup_wine(self) -> None:
        wine.cleanup(self.settings)

    def write_pid(self, pid: int) -> None:
        self.pid_file.write(pid)

    def clear_pid(self) -> None:
        self.pid_file.clear()
