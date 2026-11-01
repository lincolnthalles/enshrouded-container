"""Tests for the shared PID file contract."""

from typing import TYPE_CHECKING

from enshctl.pidfile import PidFile

if TYPE_CHECKING:
    from pathlib import Path


def test_pid_file_round_trip(tmp_path: Path) -> None:
    # GIVEN a PID file that does not exist
    pid_file = PidFile(tmp_path / "enshctl.pid")
    assert pid_file.is_active() is False

    # WHEN writing a PID
    pid_file.write(4321)

    # THEN the file is active and carries the PID
    assert pid_file.is_active() is True
    assert pid_file.path.read_text() == "4321"

    # WHEN clearing it twice
    pid_file.clear()
    pid_file.clear()

    # THEN it is inactive and clearing is idempotent
    assert pid_file.is_active() is False
