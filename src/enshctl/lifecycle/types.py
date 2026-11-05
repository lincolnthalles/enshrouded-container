"""Lifecycle value types and the server process contract."""

from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from enshctl.backup_protocol import Trigger


class ServerProcess(Protocol):
    """The subset of a running server process the lifecycle controls."""

    pid: int
    stdout: IO[bytes] | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def send_signal(self, sig: int) -> None: ...

    def kill(self) -> None: ...


class PauseControl(Protocol):
    """The lifecycle exit seam for Auto Pause."""

    def stop(self) -> None: ...

    def resume_for_shutdown(self) -> None: ...


@dataclass(frozen=True)
class ExitRequest:
    """One ordered lifecycle exit, carrying its Backup trigger and exit code."""

    trigger: Trigger | None
    exit_code: int
