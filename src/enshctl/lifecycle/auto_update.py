"""Auto Update state machine — scheduled checks, guarded downloads, and restart requests."""

import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

from enshctl.manifests import manifest_sort_key
from enshctl.presence import active_presence_veto, presence_health_veto, session_veto
from enshctl.scheduling import parse_cron

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.download.types import ManifestRecord
    from enshctl.lifecycle.pause_gate import PauseGate
    from enshctl.lifecycle.types import RestartRequest
    from enshctl.presence import PresenceTracker
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

AUTO_UPDATE_FALLBACK_INTERVAL = 3600.0
TICK_INTERVAL = 1.0


def is_auto_update_active(settings: AppSettings) -> bool:
    """Whether Auto Update is enabled for a Version spec that resolves to latest."""
    return settings.auto_update_enabled and settings.version in ("", "latest")


class AutoUpdateController:
    """Own update timing, candidate selection, guarded downloads, and restart requests."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        active_manifest: ManifestRecord,
        tracker: PresenceTracker,
        pause_gate: PauseGate,
        list_latest: Callable[[], ManifestRecord | None],
        download: Callable[[ManifestRecord], None],
        restart_request: RestartRequest,
        stream_healthy: Callable[[], bool],
        is_paused: Callable[[], bool],
        clock: Callable[[], float] = monotonic,
        wait: Callable[[threading.Event, float], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._active_manifest = active_manifest
        self._tracker = tracker
        self._pause_gate = pause_gate
        self._list_latest = list_latest
        self._download = download
        self._restart_request = restart_request
        self._stream_healthy = stream_healthy
        self._is_paused = is_paused
        self._clock = clock
        self._wait = wait or (lambda event, timeout: event.wait(timeout))
        self._stop_event = threading.Event()
        self._pending: ManifestRecord | None = None
        self._pending_downloaded = False
        self._download_retry_at = 0.0
        self._download_lock = threading.Lock()
        self._download_done = threading.Event()
        self._download_thread: threading.Thread | None = None
        self._download_manifest: ManifestRecord | None = None
        self._download_succeeded = False
        self._download_error: Exception | None = None
        self._thread: threading.Thread | None = None

    def start(self, stop_event: threading.Event) -> threading.Thread:
        """Start the daemon update loop."""
        self._stop_event = stop_event
        thread = threading.Thread(target=self._run, daemon=True, name="auto-update")
        self._thread = thread
        thread.start()
        return thread

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception:
            logger.exception("Auto Update: controller failed; continuing without updates")

    def _run_loop(self) -> None:
        next_check_at = self._clock() + self._interval()
        while not self._stop_event.is_set():
            now = self._clock()
            if now >= next_check_at:
                self._check(now)
                now = self._clock()
                next_check_at = now + self._interval()
            if self._stop_event.is_set():
                break
            self._finish_download(now)
            if self._pending is not None and not self._settings.auto_update_log_only:
                if self._pending_downloaded:
                    if self._gate_is_clear(now):
                        self._request_restart()
                        return
                elif self._should_download(now):
                    self._start_download(now)
            self._wait_for_work(next_check_at)

    def _interval(self) -> float:
        return (
            parse_cron(
                self._settings.auto_update_cron,
                fallback=AUTO_UPDATE_FALLBACK_INTERVAL,
            )
            or AUTO_UPDATE_FALLBACK_INTERVAL
        )

    def _check(self, now: float) -> None:
        if self._stop_event.is_set():
            return
        acquire = self._pause_gate.acquire_ignoring_quiet if self._is_paused() else self._pause_gate.acquire
        if not acquire(self._stop_event):
            return
        try:
            candidate = self._list_latest()
        except Exception as exc:  # noqa: BLE001 - a bad listing must not stop the updater
            if self._stop_event.is_set():
                return
            logger.warning("Auto Update: manifest check failed: %s", exc)
            self._warn_pending()
            return
        finally:
            self._pause_gate.release()
        if self._stop_event.is_set():
            return
        if candidate is None:
            logger.warning("Auto Update: manifest check returned no Manifests")
            self._warn_pending()
            return
        active_key = manifest_sort_key(self._active_manifest)
        candidate_key = manifest_sort_key(candidate)
        if (
            not self._active_manifest.timestamp
            or not candidate.timestamp
            or active_key == (0, 0, 0, 0, 0, 0)
            or candidate_key == (0, 0, 0, 0, 0, 0)
        ):
            logger.warning(
                "Auto Update: cannot compare Manifest timestamps (active=%r, candidate=%r)",
                self._active_manifest.timestamp,
                candidate.timestamp,
            )
            self._warn_pending()
            return

        if candidate_key <= active_key:
            self._warn_pending()
            return
        if self._pending is not None and candidate_key <= manifest_sort_key(self._pending):
            self._warn_pending()
            return

        self._pending = candidate
        self._pending_downloaded = False
        self._download_retry_at = now
        self._warn_pending()

    def _warn_pending(self) -> None:
        if self._stop_event.is_set() or self._pending is None:
            return
        logger.warning(
            "Auto Update: manifest %s is available (running %s)",
            self._pending.manifest_id,
            self._active_manifest.manifest_id,
        )

    def _should_download(self, now: float) -> bool:
        if (
            self._pending is None
            or self._pending_downloaded
            or self._download_thread is not None
            or now < self._download_retry_at
        ):
            return False
        return not self._settings.auto_update_download_only_when_empty or self._gate_is_clear(now)

    def _start_download(self, now: float) -> None:
        if self._stop_event.is_set() or self._pending is None or self._download_thread is not None:
            return
        acquire = self._pause_gate.acquire_ignoring_quiet if self._is_paused() else self._pause_gate.acquire
        if not acquire(self._stop_event):
            return
        acquired = True
        manifest = self._pending
        self._download_manifest = manifest
        self._download_done.clear()
        with self._download_lock:
            self._download_succeeded = False
            self._download_error = None
        thread = threading.Thread(
            target=self._download_worker,
            args=(manifest, acquired),
            daemon=True,
            name="auto-update-download",
        )
        self._download_thread = thread
        logger.info("Auto Update: downloading manifest %s", manifest.manifest_id)
        try:
            thread.start()
        except RuntimeError as exc:
            self._download_thread = None
            self._download_manifest = None
            if acquired:
                self._pause_gate.release()
            logger.warning("Auto Update: could not start download: %s", exc)
            self._download_retry_at = now + self._interval()

    def _download_worker(self, manifest: ManifestRecord, acquired: bool) -> None:
        succeeded = False
        error: Exception | None = None
        try:
            self._download(manifest)
            succeeded = True
        except Exception as exc:  # noqa: BLE001 - a bad download must not stop the server
            error = exc
        finally:
            if acquired:
                self._pause_gate.release()
            with self._download_lock:
                self._download_succeeded = succeeded
                self._download_error = error
            self._download_done.set()

    def _finish_download(self, now: float) -> None:
        thread = self._download_thread
        if thread is None or not self._download_done.is_set():
            return
        thread.join(timeout=0)
        self._download_thread = None
        manifest = self._download_manifest
        self._download_manifest = None
        with self._download_lock:
            succeeded = self._download_succeeded
            error = self._download_error
        if self._stop_event.is_set():
            return
        if not succeeded:
            logger.warning(
                "Auto Update: download of manifest %s failed: %s", manifest.manifest_id if manifest else "?", error
            )
            self._download_retry_at = now + self._interval()
            return
        if manifest is None or self._pending is None or self._pending.manifest_id != manifest.manifest_id:
            return
        self._pending_downloaded = True
        logger.info("Auto Update: manifest %s downloaded", manifest.manifest_id)

    def _gate_is_clear(self, now: float) -> bool:
        snapshot = self._tracker.snapshot()
        if presence_health_veto(snapshot, stream_healthy=self._stream_healthy()) is not None:
            return False
        if active_presence_veto(snapshot, now=now) is not None:
            return False
        if self._is_paused():
            return True
        return session_veto(snapshot, now=now) is None

    def _request_restart(self) -> None:
        if self._stop_event.is_set() or self._pending is None:
            return
        logger.info("Auto Update: restarting with manifest %s", self._pending.manifest_id)
        self._restart_request.request(self._pending)

    def _wait_for_work(self, next_check_at: float) -> None:
        now = self._clock()
        wait_seconds = max(next_check_at - now, TICK_INTERVAL)
        if self._download_thread is not None:
            wait_seconds = min(wait_seconds, TICK_INTERVAL)
        elif self._pending is not None and not self._settings.auto_update_log_only:
            if self._pending_downloaded or self._download_retry_at <= now:
                wait_seconds = min(wait_seconds, TICK_INTERVAL)
            else:
                wait_seconds = min(wait_seconds, self._download_retry_at - now)
        self._wait(self._stop_event, max(wait_seconds, 0.0))
