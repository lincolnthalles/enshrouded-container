"""Atomic Auto Pause control files and their CLI-facing values."""

import json
import logging
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from time import time
from typing import TYPE_CHECKING, Any

from enshctl.paths import AUTOPAUSE_DIR

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

STATUS_FRESHNESS = 30.0
REQUEST_TTL = 5.0
STATUS_FILE = "status.json"
REQUEST_FILE = "request"
PAUSED_FILE = "paused"
DISABLED_FILE = "disabled"


@dataclass(frozen=True)
class AutoPauseRequest:
    """One operator request consumed by the controller."""

    action: str
    token: str
    expires_at: float


@dataclass(frozen=True)
class AutoPauseStatus:
    """Small, serializable Auto Pause snapshot."""

    state: str
    players: tuple[str, ...] = ()
    pending_join: bool = False
    session_veto: bool = False
    degraded: bool = False
    paused_since: float | None = None
    last_error: str | None = None
    a2s: str = "unknown"
    last_request: str | None = None
    last_result: str | None = None
    updated_at: float = 0.0
    controller_pid: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> AutoPauseStatus | None:
        if not isinstance(data, dict):
            return None
        try:
            players = tuple(str(player) for player in data.get("players", ()))
            return cls(
                state=str(data["state"]),
                players=players,
                pending_join=bool(data.get("pending_join", False)),
                session_veto=bool(data.get("session_veto", False)),
                degraded=bool(data.get("degraded", False)),
                paused_since=_optional_float(data.get("paused_since")),
                last_error=None if data.get("last_error") is None else str(data["last_error"]),
                a2s=str(data.get("a2s", "unknown")),
                last_request=None if data.get("last_request") is None else str(data["last_request"]),
                last_result=None if data.get("last_result") is None else str(data["last_result"]),
                updated_at=float(data.get("updated_at", 0.0)),
                controller_pid=int(data.get("controller_pid", 0)),
            )
        except KeyError, TypeError, ValueError:
            return None


@dataclass(frozen=True)
class ControlFiles:
    """Files under `/data/config/autopause/` consumed by the controller and CLI."""

    root: Path = AUTOPAUSE_DIR
    puid: int = 1000
    pgid: int = 1000

    @property
    def disabled_path(self) -> Path:
        return self.root / DISABLED_FILE

    @property
    def paused_path(self) -> Path:
        return self.root / PAUSED_FILE

    @property
    def status_path(self) -> Path:
        return self.root / STATUS_FILE

    @property
    def request_path(self) -> Path:
        return self.root / REQUEST_FILE

    def is_disabled(self) -> bool:
        return self.disabled_path.exists()

    def set_disabled(self) -> None:
        self.ensure_dir()
        self.disabled_path.touch()
        self._chown(self.disabled_path)

    def clear_disabled(self) -> bool:
        return self._remove(self.disabled_path)

    def is_paused(self) -> bool:
        return self.paused_path.exists()

    def set_paused(self) -> None:
        self.ensure_dir()
        self.paused_path.touch()
        self._chown(self.paused_path)

    def clear_paused(self) -> bool:
        return self._remove(self.paused_path)

    def clear_runtime(self) -> None:
        self.clear_paused()
        self._remove(self.status_path)
        self._remove(self.request_path)

    def read_status(self) -> AutoPauseStatus | None:
        try:
            return AutoPauseStatus.from_dict(json.loads(self.status_path.read_text()))
        except FileNotFoundError:
            return None
        except OSError, ValueError:
            logger.warning("Could not read Auto Pause status %s", self.status_path)
            return None

    def write_status(self, status: AutoPauseStatus) -> None:
        self.ensure_dir()
        self._atomic_write(self.status_path, json.dumps(status.to_dict(), sort_keys=True))

    def live_status(
        self,
        *,
        now: float | None = None,
        pid_alive: Callable[[int], bool] | None = None,
    ) -> AutoPauseStatus | None:
        timestamp = time() if now is None else now
        status = self.read_status()
        if status is None or timestamp - status.updated_at > STATUS_FRESHNESS:
            return None
        check = pid_alive or _pid_alive
        if status.controller_pid <= 0 or not check(status.controller_pid):
            return None
        return status

    def write_request(self, action: str, token: str, *, now: float | None = None) -> AutoPauseRequest:
        timestamp = time() if now is None else now
        request = AutoPauseRequest(action, token, timestamp + REQUEST_TTL)
        self.ensure_dir()
        payload = {"action": request.action, "token": request.token, "expires_at": request.expires_at}
        self._atomic_write(self.request_path, json.dumps(payload, sort_keys=True))
        return request

    def consume_request(self, *, now: float | None = None) -> AutoPauseRequest | None:
        timestamp = time() if now is None else now
        try:
            raw = self.request_path.read_text()
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning("Could not read Auto Pause request %s", self.request_path)
            return None
        finally:
            self._remove(self.request_path)
        try:
            payload = json.loads(raw)
        except ValueError:
            logger.warning("Ignoring malformed Auto Pause request")
            return None
        if not isinstance(payload, dict):
            logger.warning("Ignoring malformed Auto Pause request")
            return None
        action = payload.get("action")
        token = payload.get("token")
        expires_at = _optional_float(payload.get("expires_at"))
        if not isinstance(action, str) or not isinstance(token, str) or expires_at is None:
            logger.warning("Ignoring malformed Auto Pause request")
            return None
        if expires_at < timestamp:
            return None
        return AutoPauseRequest(action, token, expires_at)

    def ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._chown(self.root)

    def _atomic_write(self, path: Path, text: str) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}")
        temporary.write_text(text)
        self._chown(temporary)
        temporary.replace(path)
        self._chown(path)

    def _chown(self, path: Path) -> None:
        with suppress(OSError):
            os.chown(path, self.puid, self.pgid)

    def _remove(self, path: Path) -> bool:
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            logger.warning("Could not remove Auto Pause file %s", path)
            return False
        return True


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
