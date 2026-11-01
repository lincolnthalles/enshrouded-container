"""PID file contract shared by the server lifecycle and the restore guard."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from enshctl.files import write_bytes_atomic
from enshctl.paths import PIDFILE

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class PidFile:
    """Presence marker for a running game server."""

    path: Path = PIDFILE

    def write(self, pid: int) -> None:
        write_bytes_atomic(self.path, str(pid).encode())

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def is_active(self) -> bool:
        return self.path.exists()
