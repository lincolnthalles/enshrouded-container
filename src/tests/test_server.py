"""Tests for server process control."""

import signal
import subprocess
from dataclasses import replace
from typing import IO, TYPE_CHECKING, cast
from unittest.mock import patch

from enshctl.lifecycle import gamelog, server
from enshctl.paths import GAME_EXE, WINE_PREFIX
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path

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


def test_signal_game_targets_exact_game_pid(tmp_path: Path) -> None:
    # GIVEN a fake proc tree with the game and a Wine service
    _make_process(tmp_path, 100, [str(GAME_EXE)], comm="enshrouded_server.exe")
    _make_process(tmp_path, 200, ["C:\\windows\\system32\\services.exe"], comm="services.exe")

    # WHEN signaling the game
    with patch("enshctl.lifecycle.server.os.kill") as mock_kill:
        delivered = server.signal_game(signal.SIGINT, proc_root=tmp_path)

    # THEN only the exact game PID is signalled
    assert delivered is True
    mock_kill.assert_called_once_with(100, signal.SIGINT)


def test_signal_game_reports_missing_game(tmp_path: Path) -> None:
    # GIVEN a proc tree without the game
    _make_process(tmp_path, 200, ["C:\\windows\\system32\\services.exe"], comm="services.exe")

    # WHEN signaling the game
    delivered = server.signal_game(signal.SIGTERM, proc_root=tmp_path)

    # THEN no signal is reported
    assert delivered is False


def test_wine_tree_discovers_game_and_services(tmp_path: Path) -> None:
    # GIVEN a game process, a wineserver, a C:\windows service, and an unrelated process
    _make_process(tmp_path, 100, [str(GAME_EXE)], comm="enshrouded_server.exe")
    _make_process(tmp_path, 200, ["wineserver"], comm="wineserver")
    _make_process(tmp_path, 300, ["C:\\windows\\system32\\services.exe"], comm="services.exe")
    _make_process(tmp_path, 400, ["/usr/bin/sleep", "1"], comm="sleep")

    # WHEN the tree is discovered with a no-op scan
    tree = server.wine_tree(proc_root=tmp_path, sleep=lambda _seconds: None, clock=lambda: 0.0)

    # THEN only the game and Wine services are included
    assert tree == server.WineTree(100, (200, 300))


def test_suspend_all_stops_the_tree(tmp_path: Path) -> None:
    # GIVEN a game and service already reported as stopped
    _make_process(tmp_path, 100, [str(GAME_EXE)], comm="enshrouded_server.exe", state="T")
    _make_process(tmp_path, 200, ["wineserver"], comm="wineserver", state="T")

    # WHEN the tree is suspended
    with patch("enshctl.lifecycle.server.signal_pid", return_value=True) as mock_signal:
        suspended = server.suspend_all(proc_root=tmp_path, sleep=lambda _seconds: None, clock=lambda: 0.0)

    # THEN both processes receive SIGSTOP and verification passes
    assert suspended is True
    assert [call.args for call in mock_signal.call_args_list] == [
        (100, signal.SIGSTOP),
        (200, signal.SIGSTOP),
    ]


def test_suspend_all_rolls_back_on_verification_failure(tmp_path: Path) -> None:
    # GIVEN a game that never reaches the stopped state
    _make_process(tmp_path, 100, [str(GAME_EXE)], comm="enshrouded_server.exe", state="S")
    _make_process(tmp_path, 200, ["wineserver"], comm="wineserver", state="S")

    # WHEN suspension verification fails
    with (
        patch("enshctl.lifecycle.server.signal_pid", return_value=True),
        patch("enshctl.lifecycle.server.resume_all", return_value=True) as mock_resume,
    ):
        suspended = server.suspend_all(proc_root=tmp_path, sleep=lambda _seconds: None, clock=lambda: 0.0)

    # THEN the whole tree is resumed and the pause is rejected
    assert suspended is False
    mock_resume.assert_called_once()


def test_resume_all_resumes_services_before_game(tmp_path: Path) -> None:
    # GIVEN a stopped game with a lower PID than its service
    _make_process(tmp_path, 100, [str(GAME_EXE)], comm="enshrouded_server.exe", state="T")
    _make_process(tmp_path, 200, ["wineserver"], comm="wineserver", state="T")
    order: list[int] = []

    def _resume(pid: int, sig: int) -> bool:
        assert sig == signal.SIGCONT
        order.append(pid)
        stat = tmp_path / str(pid) / "stat"
        stat.write_text(stat.read_text().replace(") T ", ") S "))
        return True

    # WHEN the tree resumes
    with patch("enshctl.lifecycle.server.signal_pid", side_effect=_resume):
        resumed = server.resume_all(proc_root=tmp_path, sleep=lambda _seconds: None, clock=lambda: 0.0)

    # THEN the service is signalled before the game
    assert resumed is True
    assert order == [200, 100]


def _make_process(
    root: Path,
    pid: int,
    cmdline: list[str],
    *,
    comm: str,
    state: str = "S",
) -> None:
    process = root / str(pid)
    process.mkdir()
    (process / "cmdline").write_bytes(b"\x00".join(arg.encode() for arg in cmdline) + b"\x00")
    (process / "comm").write_text(f"{comm}\n")
    (process / "stat").write_text(f"{pid} ({comm}) {state} 1 2 3\n")
    if comm == "wineserver":
        (process / "exe").symlink_to("/usr/lib64/wine/wineserver")


class _BoundedStdout:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0
        self.closed = False
        self.read_sizes: list[int] = []

    def readline(self, size: int = -1) -> bytes:
        assert size > 0, "stream reader must bound readline"
        self.read_sizes.append(size)
        if self._offset >= len(self._data):
            return b""
        end = min(len(self._data), self._offset + size)
        newline = self._data.find(b"\n", self._offset, end)
        if newline != -1:
            end = newline + 1
        chunk = self._data[self._offset : end]
        self._offset = end
        return chunk

    def close(self) -> None:
        self.closed = True


class _StreamProcess:
    def __init__(self, data: bytes) -> None:
        self.stdout = _BoundedStdout(data)


def test_stream_drains_to_eof(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a server stream with two lines
    process = _StreamProcess(b"one\ntwo\n")

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


def test_stream_calls_on_line_hook() -> None:
    # GIVEN a server stream with two lines
    process = _StreamProcess(b"one\ntwo\n")
    seen: list[str] = []

    # WHEN the reader drains it with a line hook
    thread = server.stream(cast("ServerProcess", process), on_line=seen.append)
    thread.join(timeout=1)

    # THEN every non-empty line reaches the hook
    assert seen == ["one", "two"]


def test_stream_discards_overlong_line_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a stream with a very long unterminated line followed by a normal line
    process = _StreamProcess(b"x" * 70_000 + b"\nnext\n")
    seen: list[str] = []

    # WHEN the reader drains it
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.server"):
        thread = server.stream(cast("ServerProcess", process), on_line=seen.append)
        thread.join(timeout=1)

    # THEN the overlong content is drained and the next line is relayed
    assert process.stdout.read_sizes[0] == 32_770
    assert seen == ["next"]
    assert "overlong" in caplog.text.lower()
    assert "x" * 32_770 not in caplog.text
    assert process.stdout.closed is True


def test_stream_discards_newline_terminated_overlong_line(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a newline-terminated line whose content exceeds the byte cap
    process = _StreamProcess(b"x" * 32_769 + b"\nnext\n")
    seen: list[str] = []

    # WHEN the reader drains it
    with caplog.at_level("WARNING", logger="enshctl.lifecycle.server"):
        thread = server.stream(cast("ServerProcess", process), on_line=seen.append)
        thread.join(timeout=1)

    # THEN it is discarded without draining and the next line is relayed
    assert seen == ["next"]
    assert "overlong" in caplog.text.lower()
    assert "x" * 32_769 not in caplog.text


def test_stream_relays_line_at_byte_cap() -> None:
    # GIVEN a CRLF line exactly at the maximum content byte count
    process = _StreamProcess(b"y" * 32_768 + b"\r\n")
    seen: list[str] = []

    # WHEN the reader drains it
    thread = server.stream(cast("ServerProcess", process), on_line=seen.append)
    thread.join(timeout=1)

    # THEN the line is relayed without truncation
    assert seen == ["y" * 32_768]


def test_stream_relays_final_line_without_terminator() -> None:
    # GIVEN a stream whose final line has no trailing newline
    process = _StreamProcess(b"last")
    seen: list[str] = []

    # WHEN the reader drains it
    thread = server.stream(cast("ServerProcess", process), on_line=seen.append)
    thread.join(timeout=1)

    # THEN the final line is relayed
    assert seen == ["last"]


def test_stream_survives_hook_failure(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a server stream with two lines and a hook that fails on the first
    process = _StreamProcess(b"one\ntwo\n")
    seen: list[str] = []

    def _on_line(line: str) -> None:
        if line == "one":
            message = "presence failed"
            raise RuntimeError(message)
        seen.append(line)

    # WHEN the reader drains it
    with caplog.at_level(gamelog.SERVER, logger="enshctl.lifecycle.server"):
        thread = server.stream(cast("ServerProcess", process), on_line=_on_line)
        thread.join(timeout=1)

    # THEN the failure is reported and later lines are still relayed
    assert "Presence callback failed" in caplog.text
    assert "one" in caplog.text
    assert "two" in caplog.text
    assert seen == ["two"]


def test_stream_handles_empty_stdout() -> None:
    # GIVEN a process without stdout
    class _Process:
        stdout: IO[bytes] | None = None

    # WHEN the reader starts
    thread = server.stream(cast("ServerProcess", _Process()))
    thread.join(timeout=1)

    # THEN it ends without raising
    assert thread.is_alive() is False
