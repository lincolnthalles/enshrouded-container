"""Auto Pause state machine and lifecycle seam."""

import logging
import os
import threading
import time
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from enshctl.lifecycle.control import AutoPauseStatus, ControlFiles
from enshctl.lifecycle.saves import SaveSignature, newest_save_signature
from enshctl.presence import PresenceGate, PresenceIntent, PresenceWarning, VetoCategory

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from enshctl.config import QueryEndpoint
    from enshctl.lifecycle.pause_gate import PauseGate
    from enshctl.lifecycle.wake import WakeSource
    from enshctl.presence import PresenceSnapshot, PresenceTracker
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

STATUS_INTERVAL = 10.0
STOP_JOIN_TIMEOUT = 5.0
TICK_INTERVAL = 1.0
SAVE_WAIT_TIMEOUT = 60.0
SAVE_SETTLE_TIME = 2.0
A2S_WARNING_INTERVAL = 5 * 60.0
VETO_WARNING_INTERVAL = 60.0

DISABLED = "disabled"
WAITING_FOR_READY = "waiting-for-ready"
ACTIVE = "active"
PAUSE_PENDING = "pause-pending"
PAUSED = "paused"
STOPPING = "stopping"


class _PauseProcess(Protocol):
    def suspend_all(self) -> bool: ...

    def resume_all(self) -> bool: ...


class _A2SProbe(Protocol):
    @property
    def last_local_endpoints(self) -> frozenset[tuple[str, int]]: ...

    def players(self) -> int | None: ...


class AutoPauseController:
    """Own idle timing, pause preconditions, suspension, wake, and resume."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        tracker: PresenceTracker,
        presence_gate: PresenceGate,
        process_control: _PauseProcess,
        control_files: ControlFiles,
        saves_dir: Path,
        query_endpoint: QueryEndpoint | None,
        a2s: _A2SProbe | None,
        wake_source: WakeSource,
        pause_gate: PauseGate,
        stream_healthy: Callable[[], bool],
        clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], float] = time.time,
        wait: Callable[[threading.Event, float], bool] | None = None,
        save_probe: Callable[[Path], SaveSignature | None] = newest_save_signature,
        pid: int | None = None,
    ) -> None:
        self._settings = settings
        self._tracker = tracker
        self._presence_gate = presence_gate
        self._process_control = process_control
        self._control_files = control_files
        self._saves_dir = saves_dir
        self._query_endpoint = query_endpoint
        self._a2s = a2s
        self._wake_source = wake_source
        self._pause_gate = pause_gate
        self._stream_healthy = stream_healthy
        self._clock = clock
        self._wall_clock = wall_clock
        self._wait = wait or (lambda event, timeout: event.wait(timeout))
        self._save_probe = save_probe
        self._pid = pid or os.getpid()
        self._lock = threading.RLock()
        self._latch = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = DISABLED if control_files.is_disabled() else WAITING_FOR_READY
        self._run_disabled = False
        self._last_activity_at = clock()
        self._paused_since: float | None = None
        self._last_error: str | None = None
        self._last_request: str | None = None
        self._last_result: str | None = None
        self._a2s_state = "unknown"
        self._a2s_warned_at: float | None = None
        self._last_status_at = 0.0
        self._last_veto_reason: str | None = None
        self._last_veto_at = 0.0
        self._quiescent_signature: SaveSignature | None = None
        self._save_activity_generation = 0
        self._pending_join_expired_at: float | None = None

    @property
    def state(self) -> str:
        return self._state

    def start(self, stop_event: threading.Event) -> threading.Thread:
        self._stop_event = stop_event
        thread = threading.Thread(target=self._run, daemon=True, name="auto-pause")
        self._thread = thread
        thread.start()
        return thread

    def stop(self) -> None:
        """Set the stop latch and join the controller without resuming here."""
        with self._lock:
            self._latch.set()
        self._wake_source.close()
        if self._thread is not None:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT)

    def resume_for_shutdown(self) -> None:
        """Idempotently resume any stopped Wine processes before SIGINT."""
        try:
            with self._lock:
                self._state = STOPPING
                self._wake_source.close()
                if not self._process_control.resume_all():
                    self._state = PAUSED
                    self._last_error = "shutdown resume verification failed"
                    logger.error("Auto Pause shutdown resume failed; preserving the paused marker")
                    self._write_status(force=True)
                    return
                self._pause_gate.resume()
                if not self._control_files.clear_paused():
                    self._last_error = "could not remove paused marker"
                    logger.error("Auto Pause: could not remove the paused marker during shutdown")
                self._paused_since = None
                self._write_status(force=True)
        except Exception:
            logger.exception("Auto Pause shutdown resume failed")

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:
            was_paused = self._state == PAUSED
            self._last_error = str(exc)
            self._run_disabled = True
            logger.exception("Auto Pause controller failed")
            try:
                if self._process_control.resume_all():
                    self._pause_gate.resume()
                    self._control_files.clear_paused()
                    self._state = DISABLED
                elif was_paused:
                    self._state = PAUSED
                    logger.exception("Auto Pause failure recovery could not resume the Wine tree")
                else:
                    self._pause_gate.resume()
                    self._state = DISABLED
            except Exception:
                if not was_paused:
                    self._pause_gate.resume()
                self._state = PAUSED if was_paused else DISABLED
                logger.exception("Auto Pause failure recovery could not resume the Wine tree")
            self._write_status(force=True)
        finally:
            self._wake_source.close()

    def _run_loop(self) -> None:
        self._write_status(force=True)
        while not self._stop_event.is_set() and not self._latch.is_set():
            now = self._clock()
            self._handle_disabled()
            self._expire_evidence(now)
            self._observe_pending_join()
            self._observe_session()
            self._handle_request(now)
            tick_started = self._clock()
            self._tick(now)
            self._write_status()
            if self._state != PAUSED or self._clock() == tick_started:
                self._wait_tick()

    def _wait_tick(self) -> None:
        self._wait(self._stop_event, TICK_INTERVAL)

    def _handle_disabled(self) -> None:
        if self._run_disabled:
            self._transition(DISABLED)
            return
        if self._control_files.is_disabled():
            if self._state == PAUSED and not self._resume("disabled marker"):
                return
            self._transition(DISABLED)
            return
        if self._state == DISABLED:
            snapshot = self._tracker.snapshot()
            self._transition(ACTIVE if snapshot.ready else WAITING_FOR_READY)
            self._last_activity_at = self._clock()

    def _expire_evidence(self, now: float) -> None:
        for event in self._tracker.expire(now):
            if isinstance(event, PresenceWarning):
                logger.warning("%s", event.message)

    def _observe_pending_join(self) -> None:
        snapshot = self._tracker.snapshot()
        expired_at = snapshot.pending_join_expired_at
        if self._state != DISABLED and expired_at is not None and expired_at != self._pending_join_expired_at:
            logger.warning("Auto Pause: pending player join expired without a completed join")
            self._pending_join_expired_at = expired_at
        elif expired_at is None:
            self._pending_join_expired_at = None

    def _observe_session(self) -> None:
        if self._state not in (ACTIVE, PAUSE_PENDING):
            return
        reason = self._presence_gate.diagnose().session_reason
        if reason is not None:
            self._log_veto(reason)

    def _tick(self, now: float) -> None:
        if self._state == WAITING_FOR_READY:
            if self._tracker.snapshot().ready:
                self._transition(ACTIVE)
                self._last_activity_at = now
                logger.info("Auto Pause: world is ready")
        elif self._state == ACTIVE:
            self._tick_active(now)
        elif self._state == PAUSED:
            self._tick_paused()

    def _tick_active(self, now: float) -> None:
        verdict = self._presence_gate.evaluate(PresenceIntent.PAUSE)
        if verdict.category is VetoCategory.HEALTH:
            reason = verdict.reason
            if reason is not None:
                self._log_veto(reason)
            return
        if verdict.has_activity:
            self._last_activity_at = now
        if self._settings.auto_pause_idle_timeout <= 0:
            return
        snapshot = self._tracker.snapshot()
        idle_since = max(self._last_activity_at, snapshot.last_activity_at or self._last_activity_at)
        if now - idle_since >= self._settings.auto_pause_idle_timeout:
            self._attempt_pause(force=False)

    def _tick_paused(self) -> None:
        if not self._stream_healthy():
            if not self._resume("stdout stream ended"):
                return
            self._run_disabled = True
            self._transition(DISABLED)
            return
        if self._control_files.is_disabled():
            if not self._resume("disabled marker"):
                return
            self._transition(DISABLED)
            return
        event = self._wake_source.wait(self._stop_event, TICK_INTERVAL)
        if event is not None:
            self._resume(f"wake {event.classification} from {event.source}")
        self._write_status()

    def _handle_request(self, now: float) -> None:
        request = self._control_files.consume_request(now=self._wall_clock())
        if request is None:
            return
        self._last_request = request.token
        self._last_result = "pending"
        self._write_status(force=True)
        if request.action in ("pause", "pause-force"):
            if self._state == PAUSED:
                self._last_result = "applied"
            else:
                paused = self._attempt_pause(force=request.action == "pause-force")
                self._last_result = "applied" if paused else "refused"
        elif request.action == "resume":
            if self._state == PAUSED:
                self._last_result = "applied" if self._resume("resume request") else "refused"
            else:
                self._last_activity_at = now
                self._last_result = "applied"
        elif request.action in ("reset", "reset-force"):
            snapshot = self._tracker.snapshot()
            if snapshot.players and request.action == "reset":
                self._last_result = "refused"
            else:
                self._tracker.reset(now=now)
                self._last_activity_at = now
                self._last_result = "applied"
        else:
            self._last_result = "refused"
        self._write_status(force=True)

    def _attempt_pause(self, *, force: bool) -> bool:
        if self._stop_event.is_set() or self._latch.is_set():
            return False
        reason = self._veto_reason(force=force)
        if reason is not None:
            self._log_veto(reason)
            return False
        if self._query_endpoint is None:
            self._a2s_state = "unavailable"
            self._log_veto("query endpoint unavailable")
            return False
        if not self._pause_gate.try_quiet():
            self._log_veto("background work in progress")
            return False
        try:
            self._save_activity_generation = self._tracker.snapshot().activity_generation
            if not force and not self._probe_a2s():
                return False
            self._state = PAUSE_PENDING
            self._write_status(force=True)
            if not self._wait_for_save(force=force):
                self._state = DISABLED if self._control_files.is_disabled() else ACTIVE
                self._write_status(force=True)
                return False
            if not self._wake_source.arm():
                self._log_veto("wake source unavailable")
                self._state = ACTIVE
                self._write_status(force=True)
                return False
            try:
                if not force and not self._probe_a2s():
                    return False
                if not self._save_still_quiescent():
                    self._log_veto("save changed before suspension")
                    return False
                return self._suspend_tree(force=force)
            finally:
                if self._state != PAUSED:
                    self._wake_source.close()
                    if self._state == PAUSE_PENDING:
                        self._state = DISABLED if self._control_files.is_disabled() else ACTIVE
                        self._write_status(force=True)
        finally:
            if self._state != PAUSED:
                self._pause_gate.resume()

    def _suspend_tree(self, *, force: bool) -> bool:
        with self._lock:
            if self._stop_event.is_set() or self._latch.is_set() or self._control_files.is_disabled():
                return False
            if self._veto_reason(force=force) is not None:
                return False
            if not force and self._tracker.snapshot().activity_generation != self._save_activity_generation:
                self._log_veto("player activity during save wait")
                return False
            if not self._process_control.suspend_all():
                self._last_error = "suspend verification failed"
                self._transition(ACTIVE)
                return False
            self._state = PAUSED
            self._control_files.set_paused()
            self._paused_since = self._wall_clock()
            self._last_activity_at = self._clock()
            logger.info("Auto Pause: paused the Wine tree")
            self._write_status(force=True)
            return True

    def _resume(self, reason: str) -> bool:
        with self._lock:
            if not self._process_control.resume_all():
                self._last_error = "resume verification failed"
                self._state = PAUSED
                logger.error("Auto Pause: resume failed (%s); preserving the paused state", reason)
                self._write_status(force=True)
                return False
            self._pause_gate.resume()
            self._wake_source.close()
            if not self._control_files.clear_paused():
                self._last_error = "could not remove paused marker"
                logger.error("Auto Pause: could not remove the paused marker")
            self._paused_since = None
            self._state = DISABLED if self._control_files.is_disabled() else ACTIVE
            self._last_activity_at = self._clock()
            logger.info("Auto Pause: resumed (%s)", reason)
            self._write_status(force=True)
            return True

    def _veto_reason(self, *, force: bool) -> str | None:
        if not self._settings.auto_pause_enabled:
            return "auto pause disabled"
        if self._control_files.is_disabled():
            return "disabled marker"
        intent = PresenceIntent.FORCED_PAUSE if force else PresenceIntent.PAUSE
        return self._presence_gate.evaluate(intent).reason

    def _pending_join(self, snapshot: PresenceSnapshot, now: float) -> bool:
        return snapshot.pending_join_until is not None and now < snapshot.pending_join_until

    def _probe_a2s(self) -> bool:
        if self._a2s is None:
            self._a2s_state = "unavailable"
            return False
        result = self._a2s.players()
        self._wake_source.ignore_source_endpoints(self._a2s.last_local_endpoints)
        if result is None:
            self._a2s_state = "unreliable"
            self._warn_a2s()
            return True
        self._a2s_state = "ok"
        if result > 0:
            self._last_activity_at = self._clock()
            logger.info("Auto Pause: A2S reports %d player(s); staying awake", result)
            return False
        return True

    def _warn_a2s(self) -> None:
        now = self._clock()
        if self._a2s_warned_at is not None and now - self._a2s_warned_at < A2S_WARNING_INTERVAL:
            return
        self._a2s_warned_at = now
        logger.warning("Auto Pause: A2S probe timed out; continuing with log-derived presence")

    def _wait_for_save(self, *, force: bool) -> bool:
        signature = self._save_probe(self._saves_dir)
        if signature is None:
            logger.warning("Auto Pause: no top-level *.ksd save found; skipping this pause")
            return False
        while not self._interrupted(force=force):
            changed = self._wait_for_signature_change(signature, force=force)
            if changed is None:
                logger.warning("Auto Pause: no new save within 60s; skipping this pause")
                return False
            if not self._settle(force=force):
                return False
            current = self._save_probe(self._saves_dir)
            if current is None:
                logger.warning("Auto Pause: save disappeared while settling; skipping this pause")
                return False
            if current == changed:
                self._quiescent_signature = current
                return True
            signature = current
        return False

    def _wait_for_signature_change(self, signature: SaveSignature, *, force: bool) -> SaveSignature | None:
        deadline = self._clock() + SAVE_WAIT_TIMEOUT
        while self._clock() < deadline:
            if self._interrupted(force=force):
                return None
            current = self._save_probe(self._saves_dir)
            if current is not None and current != signature:
                return current
            self._write_status()
            if self._wait(self._stop_event, TICK_INTERVAL):
                return None
        return None

    def _settle(self, *, force: bool) -> bool:
        deadline = self._clock() + SAVE_SETTLE_TIME
        while self._clock() < deadline:
            if self._interrupted(force=force):
                return False
            self._write_status()
            remaining = deadline - self._clock()
            if self._wait(self._stop_event, min(0.25, remaining)):
                return False
        return not self._interrupted(force=force)

    def _interrupted(self, *, force: bool) -> bool:
        if self._stop_event.is_set() or self._latch.is_set() or self._control_files.is_disabled():
            return True
        if self._control_files.request_path.exists():
            return True
        intent = PresenceIntent.FORCED_SAVE_WAIT if force else PresenceIntent.SAVE_WAIT
        if not self._presence_gate.evaluate(intent).is_allowed:
            return True
        return not force and self._tracker.snapshot().activity_generation != self._save_activity_generation

    def _save_still_quiescent(self) -> bool:
        if self._quiescent_signature is None:
            return False
        current = self._save_probe(self._saves_dir)
        return current == self._quiescent_signature

    def _transition(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self._write_status(force=True)

    def _write_status(self, *, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_status_at < STATUS_INTERVAL:
            return
        self._last_status_at = now
        snapshot = self._tracker.snapshot()
        verdict = self._presence_gate.diagnose()
        self._control_files.write_status(
            AutoPauseStatus(
                state=self._state,
                players=tuple(player.display_name for player in snapshot.players),
                pending_join=self._pending_join(snapshot, now),
                session_veto=verdict.session_veto,
                degraded=snapshot.degraded,
                paused_since=self._paused_since,
                last_error=self._last_error,
                wake_filter=self._settings.auto_pause_wake_filter,
                a2s=self._a2s_state,
                last_request=self._last_request,
                last_result=self._last_result,
                updated_at=self._wall_clock(),
                controller_pid=self._pid,
            )
        )

    def _log_veto(self, reason: str) -> None:
        now = self._clock()
        if reason == self._last_veto_reason and now - self._last_veto_at < VETO_WARNING_INTERVAL:
            return
        self._last_veto_reason = reason
        self._last_veto_at = now
        logger.warning("Auto Pause: cannot pause: %s", reason)
