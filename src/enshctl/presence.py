"""Connected-player tracking and pause evidence derived from dedicated server output."""

import re
import threading
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

MAX_HANDLES = 64
MAX_PENDING_NAMES = 16
MAX_NAME_LENGTH = 64
MAX_PARSED_LINE = 8192
MAX_SESSION_MACHINES = 64
UNNAMED_HANDLE_GRACE = 5 * 60.0
PENDING_JOIN_WINDOW = 60.0
SESSION_BLOCK_TIMEOUT = 90.0

_HANDLE_PATTERN = r"\d+\(\d+\)"
_LOG_PREFIX = re.compile(r"^(?:\[[^\]]+\]\s+){0,2}(?P<message>.*)$")
_REMOTE_PLAYER_ADDED = re.compile(rf"Remote player added\. Player handle: (?P<handle>{_HANDLE_PATTERN})")
_MACHINE_LOGIN = re.compile(rf"Machine '\d+': Player '(?P<handle>{_HANDLE_PATTERN})' logged in")
_PLAYER_NAME = re.compile(r"Player '(?P<name>.*)' logged in with Permissions:")
_PLAYER_REMOVED = re.compile(rf"Player removed\. Player handle: (?P<handle>{_HANDLE_PATTERN})")
_REMOVE_ENTITY = re.compile(r"Remove Entity for Player '(?P<name>.*)'")
_SESSION_ACCEPTED = re.compile(r"Session accepted with peer \(steamid:\d+\)")
_AUTHENTICATED = re.compile(r"Client '\d+' authenticated by steam")
_RUN_MARKER = re.compile(r"Switching state from LoadEcsScene to Run(?:\s+after\s+[\d.]+\s*ms)?")
_SESSION_BLOCK_START = re.compile(r"-{3,}\s+Session\s+-{3,}")
_SESSION_BLOCK_END = re.compile(r"-{10,}")
_SESSION_MACHINE = re.compile(
    r"\s*m#(?P<index>\d+)\(\d+\):\s+up\s+\d+\s+\(\d+\),\s+down\s+\d+\s+\(\d+\),\s+"
    r"remote\s+\d+\s+\(\d+\),\s+limit\s+\d+,\s+lost\s+\d+,\s+ping\s+\d+\s+ms,\s+\w+"
)
_SESSION_MACHINE_PREFIX = re.compile(r"\s*m#")


@dataclass(frozen=True)
class Player:
    handle: str
    name: str | None = None
    leaving: bool = False

    @property
    def display_name(self) -> str:
        return self.name or self.handle


@dataclass(frozen=True)
class PresenceSnapshot:
    players: tuple[Player, ...]
    pending_join_until: float | None = None
    pending_join_expired_at: float | None = None
    ready: bool = False
    last_activity_at: float | None = None
    session_machines: frozenset[int] | None = None
    session_complete_at: float | None = None
    session_malformed: bool = False
    degraded: bool = False
    activity_generation: int = 0

    @property
    def handles(self) -> frozenset[str]:
        return frozenset(player.handle for player in self.players)

    @property
    def is_empty(self) -> bool:
        return not self.players

    @property
    def has_pending_join(self) -> bool:
        return self.pending_join_until is not None


@dataclass(frozen=True)
class PlayerEvent:
    handle: str
    name: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or self.handle


@dataclass(frozen=True)
class PlayerJoined(PlayerEvent):
    pass


@dataclass(frozen=True)
class PlayerLeft(PlayerEvent):
    pass


@dataclass(frozen=True)
class PresenceWarning:
    message: str


type PresenceEvent = PlayerJoined | PlayerLeft | PresenceWarning


def _message(line: str) -> str:
    match = _LOG_PREFIX.match(line)
    return match["message"] if match is not None else line


@dataclass
class _Entry:
    handle: str
    name: str | None
    added_at: float
    leaving: bool = False


class PresenceTracker:
    """Thread-safe connected-player set and pause evidence from one stdout stream."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or monotonic
        self._lock = threading.Lock()
        self._players: dict[str, _Entry] = {}
        self._pending_names: deque[str] = deque()
        self._queue_warned: set[str] = set()
        self._cap_warned = False
        self._degraded = False
        self._pending_join_until: float | None = None
        self._pending_join_expired_at: float | None = None
        self._ready = False
        self._last_activity_at: float | None = None
        self._activity_generation = 0
        self._session_machines: frozenset[int] | None = None
        self._session_complete_at: float | None = None
        self._session_malformed = False
        self._session_open_since: float | None = None
        self._session_indices: set[int] = set()
        self._session_open_malformed = False
        self._session_overdue_warned = False

    def observe(self, line: str, now: float | None = None) -> tuple[PresenceEvent, ...]:
        """Process one server output line and return roster events."""
        if len(line) > MAX_PARSED_LINE:
            return ()
        timestamp = self._clock() if now is None else now
        message = _message(line)
        with self._lock:
            events = list(self._expire_unnamed(timestamp))
            events.extend(self._expire_pending(timestamp))
            events.extend(self._expire_session(timestamp))
            events.extend(self._apply_line(message, timestamp))
            return tuple(events)

    def expire(self, now: float | None = None) -> tuple[PresenceEvent, ...]:
        """Expire unnamed handles, pending joins, and an overdue session block."""
        timestamp = self._clock() if now is None else now
        with self._lock:
            events = list(self._expire_unnamed(timestamp))
            events.extend(self._expire_pending(timestamp))
            events.extend(self._expire_session(timestamp))
            return tuple(events)

    def snapshot(self) -> PresenceSnapshot:
        """Return an immutable view of the current roster and pause evidence."""
        with self._lock:
            return PresenceSnapshot(
                tuple(Player(entry.handle, entry.name, entry.leaving) for entry in self._players.values()),
                pending_join_until=self._pending_join_until,
                pending_join_expired_at=self._pending_join_expired_at,
                ready=self._ready,
                last_activity_at=self._last_activity_at,
                session_machines=self._session_machines,
                session_complete_at=self._session_complete_at,
                session_malformed=self._session_malformed,
                degraded=self._degraded,
                activity_generation=self._activity_generation,
            )

    def reset(self, now: float | None = None) -> None:
        """Clear roster and pause evidence without touching the game process."""
        timestamp = self._clock() if now is None else now
        with self._lock:
            self._players.clear()
            self._pending_names.clear()
            self._queue_warned.clear()
            self._cap_warned = False
            self._degraded = False
            self._pending_join_until = None
            self._pending_join_expired_at = None
            self._session_machines = None
            self._session_complete_at = None
            self._session_malformed = False
            self._session_open_since = None
            self._session_indices.clear()
            self._session_open_malformed = False
            self._session_overdue_warned = False
            self._last_activity_at = timestamp

    def _apply_line(self, message: str, now: float) -> list[PresenceEvent]:
        if _SESSION_BLOCK_START.fullmatch(message):
            return self._start_session_block(now)
        if _SESSION_BLOCK_END.fullmatch(message):
            return self._close_session_block(now)
        if self._session_open_since is not None:
            if match := _SESSION_MACHINE.fullmatch(message):
                index = int(match["index"])
                if index in self._session_indices:
                    return []
                if len(self._session_indices) >= MAX_SESSION_MACHINES:
                    self._session_open_malformed = True
                    return []
                self._session_indices.add(index)
                return []
            if _SESSION_MACHINE_PREFIX.match(message):
                self._session_open_malformed = True
                return []
        if _SESSION_ACCEPTED.fullmatch(message) or _AUTHENTICATED.fullmatch(message):
            self._touch(now)
            self._pending_join_until = now + PENDING_JOIN_WINDOW
            self._pending_join_expired_at = None
            return []
        if match := _REMOTE_PLAYER_ADDED.fullmatch(message):
            self._touch(now)
            self._clear_pending_join()
            return self._add_handle(match["handle"], now)
        if match := _MACHINE_LOGIN.fullmatch(message):
            self._touch(now)
            self._clear_pending_join()
            return self._add_handle(match["handle"], now)
        if match := _PLAYER_NAME.fullmatch(message):
            return self._attach_name(match["name"], now)
        if match := _REMOVE_ENTITY.fullmatch(message):
            self._touch(now)
            return self._mark_leaving(match["name"])
        if match := _PLAYER_REMOVED.fullmatch(message):
            self._touch(now)
            return self._remove_handle(match["handle"])
        if _RUN_MARKER.fullmatch(message):
            self._ready = True
            self._touch(now)
        return []

    def _touch(self, now: float) -> None:
        self._last_activity_at = now
        self._activity_generation += 1

    def _clear_pending_join(self) -> None:
        self._pending_join_until = None
        self._pending_join_expired_at = None

    def _add_handle(self, handle: str, now: float) -> list[PresenceEvent]:
        entry = self._players.get(handle)
        if entry is not None:
            return self._enqueue_name(handle)

        if len(self._players) >= MAX_HANDLES:
            self._degraded = True
            if self._cap_warned:
                return []
            self._cap_warned = True
            return [PresenceWarning(f"Player handle cap reached; ignoring {handle}")]

        self._players[handle] = _Entry(handle, None, now)
        events: list[PresenceEvent] = [PlayerJoined(handle)]
        events.extend(self._enqueue_name(handle))
        return events

    def _enqueue_name(self, handle: str) -> list[PresenceEvent]:
        entry = self._players.get(handle)
        if entry is None or entry.name is not None or handle in self._pending_names:
            return []
        if len(self._pending_names) >= MAX_PENDING_NAMES:
            if handle in self._queue_warned:
                return []
            self._queue_warned.add(handle)
            return [PresenceWarning(f"Name pairing queue full; {handle} will use the unnamed fallback")]
        self._queue_warned.discard(handle)
        self._pending_names.append(handle)
        return []

    def _attach_name(self, raw_name: str, now: float) -> list[PresenceEvent]:
        name = _sanitize_name(raw_name)
        if name is None:
            return [PresenceWarning("Ignoring empty player name")]
        self._touch(now)
        self._clear_pending_join()

        handle: str | None = None
        while self._pending_names:
            candidate = self._pending_names.popleft()
            entry = self._players.get(candidate)
            if entry is not None and entry.name is None:
                handle = candidate
                break
        if handle is None:
            for candidate, entry in self._players.items():
                if entry.name is None:
                    handle = candidate
                    break
        if handle is None:
            return [PresenceWarning(f"Player name {name!r} has no unnamed handle")]

        self._players[handle].name = name
        self._discard_pairing(handle)
        return []

    def _mark_leaving(self, raw_name: str) -> list[PresenceEvent]:
        name = _sanitize_name(raw_name)
        if name is None:
            return [PresenceWarning("Ignoring empty player name in Remove Entity")]
        for entry in self._players.values():
            if entry.name == name and not entry.leaving:
                entry.leaving = True
                return []
        return [PresenceWarning(f"Remove Entity for unknown player {name!r}")]

    def _remove_handle(self, handle: str) -> list[PresenceEvent]:
        entry = self._players.pop(handle, None)
        if entry is None:
            return [PresenceWarning(f"Player removed for unknown handle {handle}")]
        self._discard_pairing(handle)
        self._reset_cap_warning()
        return [PlayerLeft(handle, entry.name)]

    def _expire_unnamed(self, now: float) -> list[PresenceEvent]:
        expired = [
            handle
            for handle, entry in self._players.items()
            if entry.name is None and now - entry.added_at >= UNNAMED_HANDLE_GRACE
        ]
        events: list[PresenceEvent] = []
        for handle in expired:
            self._players.pop(handle)
            self._discard_pairing(handle)
            events.append(PresenceWarning(f"Unnamed player handle {handle} expired after {int(UNNAMED_HANDLE_GRACE)}s"))
        if expired:
            self._reset_cap_warning()
        return events

    def _expire_pending(self, now: float) -> list[PresenceEvent]:
        if self._pending_join_until is None or now < self._pending_join_until:
            return []
        self._pending_join_until = None
        self._pending_join_expired_at = now
        return []

    def _start_session_block(self, now: float) -> list[PresenceEvent]:
        if self._session_open_since is not None:
            self._session_malformed = True
        self._session_open_since = now
        self._session_indices.clear()
        self._session_open_malformed = False
        self._session_overdue_warned = False
        return []

    def _close_session_block(self, now: float) -> list[PresenceEvent]:
        if self._session_open_since is None:
            return []
        duration = now - self._session_open_since
        malformed = self._session_open_malformed or duration >= SESSION_BLOCK_TIMEOUT or 0 not in self._session_indices
        self._session_machines = frozenset(self._session_indices)
        self._session_complete_at = now
        self._session_malformed = malformed
        if any(index > 0 for index in self._session_indices):
            self._touch(now)
        self._session_open_since = None
        self._session_indices.clear()
        self._session_open_malformed = False
        return []

    def _expire_session(self, now: float) -> list[PresenceEvent]:
        if self._session_open_since is None or self._session_overdue_warned:
            return []
        if now - self._session_open_since < SESSION_BLOCK_TIMEOUT:
            return []
        self._session_malformed = True
        self._session_overdue_warned = True
        return []

    def _discard_pairing(self, handle: str) -> None:
        if handle in self._pending_names:
            self._pending_names.remove(handle)
        self._queue_warned.discard(handle)

    def _reset_cap_warning(self) -> None:
        if len(self._players) < MAX_HANDLES:
            self._cap_warned = False
            self._degraded = False


def _sanitize_name(raw_name: str) -> str | None:
    stripped = raw_name.strip()
    if not stripped:
        return None
    sanitized = "".join("?" if ord(char) < 32 or 0x7F <= ord(char) <= 0x9F else char for char in stripped)
    return sanitized[:MAX_NAME_LENGTH]
