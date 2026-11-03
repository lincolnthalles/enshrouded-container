"""Tests for server process control."""

import signal
import subprocess
from dataclasses import replace
from typing import IO, TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from enshctl.lifecycle import gamelog, server
from enshctl.paths import GAME_EXE, WINE_PREFIX
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    import pytest
    from enshctl.lifecycle.types import ServerProcess


def test_start_builds_launch_command_and_environment() -> None:
    # GIVEN explicit settings, an inherited environment, and a DLL override
    settings = replace(
        AppSettings(),
        winearch="win64",
        winedebug="-all",
        home="/home/steam",
        puid=1234,
        winedlloverrides="dinput8=n",
    )

    with patch("enshctl.lifecycle.server.subprocess.Popen") as mock_popen:
        # WHEN the server starts
        result = server.start(settings, source={"PATH": "/usr/bin"})

    # THEN it launches the game as steam under the virtual display with the resolved environment
    assert result is mock_popen.return_value
    assert mock_popen.call_args.args[0] == [
        "/usr/bin/runuser",
        "-u",
        "steam",
        "--",
        "xvfb-run",
        "--auto-servernum",
        '--server-args="-screen 0 90x90x1"',
        "wine",
        str(GAME_EXE),
    ]
    assert mock_popen.call_args.kwargs == {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "cwd": "/data/gameserver",
        "env": {
            "PATH": "/usr/bin",
            "WINEPREFIX": str(WINE_PREFIX),
            "WINEARCH": "win64",
            "WINEDEBUG": "-all",
            "HOME": "/home/steam",
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "WINEDLLOVERRIDES": "dinput8=n",
            "XDG_RUNTIME_DIR": "/var/run/user/1234",
        },
    }


def test_signal_uses_pkill() -> None:
    # GIVEN a running game server
    with patch("enshctl.lifecycle.server.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # WHEN signaling the game
        delivered = server.signal(signal.SIGINT)
    # THEN pkill targets the game binary as steam
    assert delivered is True
    assert mock_run.call_args.args[0] == [
        "/usr/bin/runuser",
        "-u",
        "steam",
        "--",
        "pkill",
        f"-{signal.SIGINT}",
        "-f",
        "enshrouded_server.exe",
    ]


def test_signal_reports_no_match() -> None:
    # GIVEN no process matches the game binary
    with patch("enshctl.lifecycle.server.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        # WHEN signaling the game
        delivered = server.signal(signal.SIGTERM)
    # THEN delivery is reported as false
    assert delivered is False


def test_stream_drains_to_eof(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a server stream with two lines
    class _Stdout:
        def __init__(self) -> None:
            self._lines = [b"one\n", b"two\n", b""]
            self.closed = False

        def readline(self) -> bytes:
            return self._lines.pop(0)

        def close(self) -> None:
            self.closed = True

    class _Process:
        def __init__(self) -> None:
            self.stdout = _Stdout()

    process = _Process()

    # WHEN the reader drains it
    with caplog.at_level("INFO", logger="enshctl.lifecycle.server"):
        thread = server.stream(cast("ServerProcess", process))
        thread.join(timeout=1)

    # THEN both lines are relayed at the game-server level and the stream is closed
    assert thread.is_alive() is False
    assert "one" in caplog.text
    assert "two" in caplog.text
    assert any(record.levelno == gamelog.SERVER for record in caplog.records)
    assert process.stdout.closed is True


def test_stream_handles_empty_stdout() -> None:
    # GIVEN a process without stdout
    class _Process:
        stdout: IO[bytes] | None = None

    # WHEN the reader starts
    thread = server.stream(cast("ServerProcess", _Process()))
    thread.join(timeout=1)

    # THEN it ends without raising
    assert thread.is_alive() is False
