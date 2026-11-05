"""Connected-player tracking derived from dedicated server output."""

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
UNNAMED_HANDLE_GRACE = 5 * 60.0

_HANDLE_PATTERN = r"\d+\(\d+\)"
_LOG_PREFIX = re.compile(r"^\[[^\]]+\]\s+\[[^\]]+\]\s+(?P<message>.*)$")
_REMOTE_PLAYER_ADDED = re.compile(rf"Remote player added\. Player handle: (?P<handle>{_HANDLE_PATTERN})")
_MACHINE_LOGIN = re.compile(rf"Machine '\d+': Player '(?P<handle>{_HANDLE_PATTERN})' logged in")
_PLAYER_NAME = re.compile(r"Player '(?P<name>.*)' logged in with Permissions:")
_PLAYER_REMOVED = re.compile(rf"Player removed\. Player handle: (?P<handle>{_HANDLE_PATTERN})")


@dataclass(frozen=True)
class Player:
    handle: str
    name: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or self.handle


@dataclass(frozen=True)
class PresenceSnapshot:
    players: tuple[Player, ...]

    @property
    def handles(self) -> frozenset[str]:
        return frozenset(player.handle for player in self.players)

    @property
    def is_empty(self) -> bool:
        return not self.players


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


class PresenceTracker:
    """Thread-safe connected-player set derived from one stdout stream."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or monotonic
        self._lock = threading.Lock()
        self._players: dict[str, _Entry] = {}
        self._pending_names: deque[str] = deque()
        self._queue_warned: set[str] = set()
        self._cap_warned = False

    def observe(self, line: str, now: float | None = None) -> tuple[PresenceEvent, ...]:
        """Process one server output line and return roster events."""
        if len(line) > MAX_PARSED_LINE:
            return ()
        timestamp = self._clock() if now is None else now
        message = _message(line)
        with self._lock:
            events = list(self._expire_unnamed(timestamp))
            events.extend(self._apply_line(message, timestamp))
            return tuple(events)

    def expire(self, now: float | None = None) -> tuple[PresenceEvent, ...]:
        """Expire unnamed handles that have outlived the grace period."""
        timestamp = self._clock() if now is None else now
        with self._lock:
            return tuple(self._expire_unnamed(timestamp))

    def snapshot(self) -> PresenceSnapshot:
        """Return an immutable view of the current roster."""
        with self._lock:
            return PresenceSnapshot(tuple(Player(entry.handle, entry.name) for entry in self._players.values()))

    def _apply_line(self, message: str, now: float) -> list[PresenceEvent]:
        if match := _REMOTE_PLAYER_ADDED.fullmatch(message):
            return self._add_handle(match["handle"], now)
        if match := _MACHINE_LOGIN.fullmatch(message):
            return self._add_handle(match["handle"], now)
        if match := _PLAYER_NAME.fullmatch(message):
            return self._attach_name(match["name"])
        if match := _PLAYER_REMOVED.fullmatch(message):
            return self._remove_handle(match["handle"])
        return []

    def _add_handle(self, handle: str, now: float) -> list[PresenceEvent]:
        entry = self._players.get(handle)
        if entry is not None:
            return self._enqueue_name(handle)

        if len(self._players) >= MAX_HANDLES:
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

    def _attach_name(self, raw_name: str) -> list[PresenceEvent]:
        name = _sanitize_name(raw_name)
        if name is None:
            return [PresenceWarning("Ignoring empty player name")]

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

    def _discard_pairing(self, handle: str) -> None:
        if handle in self._pending_names:
            self._pending_names.remove(handle)
        self._queue_warned.discard(handle)

    def _reset_cap_warning(self) -> None:
        if len(self._players) < MAX_HANDLES:
            self._cap_warned = False


def _sanitize_name(raw_name: str) -> str | None:
    stripped = raw_name.strip()
    if not stripped:
        return None
    sanitized = "".join("?" if ord(char) < 32 or 0x7F <= ord(char) <= 0x9F else char for char in stripped)
    return sanitized[:MAX_NAME_LENGTH]
