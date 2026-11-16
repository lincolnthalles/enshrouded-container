"""Scheduled in-process restart controller — timing, player grace, and one restart request."""

import logging
import threading
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

from enshctl.scheduling import Schedule, format_next_run, parse_schedule

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

SCHEDULE_POLL = 60.0
GRACE_POLL = 1.0
FREQUENT_WARNING_SECONDS = 15 * 60.0


def start_auto_restart(
    settings: AppSettings,
    *,
    stop_event: threading.Event,
    players_present: Callable[[], bool],
    request_restart: Callable[[], None],
    rollback_active: bool = False,
    clock: Callable[[], float] = monotonic,
    wall_clock: Callable[[], datetime] | None = None,
    wait: Callable[[threading.Event, float], bool] | None = None,
) -> threading.Thread | None:
    """Validate the configured schedule and start the daemon controller when it can run."""
    if not settings.auto_restart_enabled:
        return None
    wall = wall_clock or _local_now
    try:
        schedule = parse_schedule(settings.auto_restart_cron)
    except ValueError as exc:
        logger.log(logging.ERROR, "Auto Restart: %s", exc)
        return None
    delay = schedule.next_delay(now=wall(), elapsed=0.0)
    if delay is None:
        logger.error(
            "Auto Restart: AUTO_RESTART_CRON %r has no trigger within five years; not starting",
            settings.auto_restart_cron,
        )
        return None
    if rollback_active:
        logger.warning("Auto Restart: disabled while auto rollback is active")
        return None
    if delay < FREQUENT_WARNING_SECONDS:
        logger.warning(
            "Auto Restart: schedule %r is very frequent (next run %s)",
            settings.auto_restart_cron,
            format_next_run(delay),
        )
    logger.info(
        "Auto Restart: enabled (schedule=%s, next run %s)",
        settings.auto_restart_cron,
        format_next_run(delay),
    )
    controller = AutoRestartController(
        schedule=schedule,
        expression=settings.auto_restart_cron,
        max_delay=settings.auto_restart_max_delay,
        players_present=players_present,
        request_restart=request_restart,
        clock=clock,
        wall_clock=wall,
        wait=wait,
    )
    return controller.start(stop_event)


class AutoRestartController:
    """Own schedule timing and request one scheduled restart per lifecycle."""

    def __init__(
        self,
        *,
        schedule: Schedule,
        expression: str,
        max_delay: int,
        players_present: Callable[[], bool],
        request_restart: Callable[[], None],
        clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        wait: Callable[[threading.Event, float], bool] | None = None,
    ) -> None:
        self._schedule = schedule
        self._expression = expression
        self._max_delay = max_delay
        self._players_present = players_present
        self._request_restart = request_restart
        self._clock = clock
        self._wall_clock = wall_clock or _local_now
        self._wait = wait or (lambda event, timeout: event.wait(timeout))
        self._stop_event = threading.Event()
        self._started_at = 0.0
        self._thread: threading.Thread | None = None

    def start(self, stop_event: threading.Event) -> threading.Thread:
        """Start the daemon restart loop."""
        self._stop_event = stop_event
        self._started_at = self._clock()
        thread = threading.Thread(target=self._run, daemon=True, name="auto-restart")
        self._thread = thread
        thread.start()
        return thread

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception:
            logger.exception("Auto Restart: controller failed; continuing without scheduled restarts")

    def _run_loop(self) -> None:
        due_at = self._next_due_at()
        if due_at is None:
            logger.error(
                "Auto Restart: AUTO_RESTART_CRON %r has no next trigger within five years; stopping",
                self._expression,
            )
            return
        while not self._stop_event.is_set():
            now = self._clock()
            if now >= due_at:
                break
            self._wait(self._stop_event, min(due_at - now, SCHEDULE_POLL))
            if self._stop_event.is_set():
                return
            now = self._clock()
            if now >= due_at:
                break
            due_at = self._next_due_at()
            if due_at is None:
                logger.error(
                    "Auto Restart: AUTO_RESTART_CRON %r has no next trigger within five years; stopping",
                    self._expression,
                )
                return
        if self._stop_event.is_set():
            return
        self._run_due(due_at)

    def _next_due_at(self) -> float | None:
        now = self._clock()
        delay = self._schedule.next_delay(
            now=self._wall_clock(),
            elapsed=now - self._started_at,
        )
        if delay is None:
            return None
        return now + delay

    def _run_due(self, due_at: float) -> None:
        if self._stop_event.is_set():
            return
        if self._max_delay <= 0 or not self._players_present():
            self._request()
            return
        deadline = due_at + self._max_delay
        logger.warning(
            "Auto Restart: due but players are online; waiting up to %ds for an empty server",
            self._max_delay,
        )
        while not self._stop_event.is_set():
            if not self._players_present():
                self._request()
                return
            now = self._clock()
            if now >= deadline:
                logger.warning("Auto Restart: grace window expired with players online; restarting anyway")
                self._request()
                return
            self._wait(self._stop_event, min(deadline - now, GRACE_POLL))

    def _request(self) -> None:
        if self._stop_event.is_set():
            return
        logger.info("Auto Restart: starting scheduled restart")
        self._request_restart()


def _local_now() -> datetime:
    return datetime.now(tz=UTC).astimezone()
