"""Player roster console reporting."""

import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

from enshctl.presence import PlayerJoined, PlayerLeft, PresenceWarning

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.presence import PresenceEvent, PresenceTracker
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

_SUMMARY_WAIT_CHUNK = 60


class PlayerReporter:
    """Emit roster lines without coupling presence tracking to output settings."""

    def __init__(
        self,
        tracker: PresenceTracker,
        settings: AppSettings,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._tracker = tracker
        self._settings = settings
        self._clock = clock or monotonic
        self._lock = threading.Lock()

    def observe(self, line: str) -> None:
        """Track one server output line and emit its roster events."""
        with self._lock:
            self._emit(self._tracker.observe(line, now=self._clock()))

    def log_summary(self) -> None:
        """Expire stale handles and log the current roster."""
        with self._lock:
            self._emit(self._tracker.expire(now=self._clock()))
            if not self._settings.player_log:
                return
            snapshot = self._tracker.snapshot()
            if not snapshot.players:
                logger.info("Players online: 0")
                return
            names = ", ".join(player.display_name for player in snapshot.players)
            logger.info("Players online: %d - %s", len(snapshot.players), names)

    def start(self, stop_event: threading.Event) -> threading.Thread | None:
        """Start the periodic summary thread, if output and an interval are enabled."""
        if not self._settings.player_log or self._settings.player_poll_interval <= 0:
            return None
        thread = threading.Thread(target=self._run_summary, args=(stop_event,), daemon=True, name="player-presence")
        thread.start()
        return thread

    def _run_summary(self, stop_event: threading.Event) -> None:
        interval = self._settings.player_poll_interval
        if interval <= 0:
            return
        remaining = interval
        while not stop_event.is_set():
            chunk = min(_SUMMARY_WAIT_CHUNK, remaining)
            if stop_event.wait(chunk):
                return
            remaining -= chunk
            if remaining <= 0:
                self.log_summary()
                remaining = interval

    def _emit(self, events: tuple[PresenceEvent, ...]) -> None:
        for event in events:
            match event:
                case PlayerJoined():
                    if self._settings.player_log:
                        logger.info("Player joined: %s", event.display_name)
                case PlayerLeft():
                    if self._settings.player_log:
                        logger.info("Player left: %s", event.display_name)
                case PresenceWarning():
                    logger.warning("%s", event.message)
