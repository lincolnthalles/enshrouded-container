"""Tests for game log discovery and tailing."""

import os
import threading
from typing import TYPE_CHECKING
from unittest.mock import patch

from enshctl.lifecycle import gamelog

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_find_latest_returns_newest_by_mtime(tmp_path: Path) -> None:
    # GIVEN two log files with different modification times
    older = tmp_path / "older.log"
    newer = tmp_path / "newer.log"
    older.write_text("old")
    newer.write_text("new")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    # WHEN searching the directory
    found = gamelog.find_latest(search_roots=(tmp_path,))

    # THEN the newest log is returned
    assert found == newer


def test_find_latest_searches_nested_logs_directory(tmp_path: Path) -> None:
    # GIVEN a log inside a nested logs directory
    nested = tmp_path / "nested" / "logs"
    nested.mkdir(parents=True)
    log = nested / "game.log"
    log.write_text("line")

    # WHEN searching the root
    found = gamelog.find_latest(search_roots=(tmp_path,))

    # THEN the nested log is found
    assert found == log


def test_find_latest_returns_none_without_logs(tmp_path: Path) -> None:
    # GIVEN a directory with no log files
    (tmp_path / "notes.txt").write_text("not a log")

    # WHEN searching the directory
    found = gamelog.find_latest(search_roots=(tmp_path,))

    # THEN no log is returned
    assert found is None


def test_tail_relays_lines_and_reports_count(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a tail process that emits two lines before EOF
    class _Stdout:
        def __init__(self) -> None:
            self._lines = [b"one\n", b"two\n", b""]

        def readline(self) -> bytes:
            return self._lines.pop(0)

    class _Process:
        def __init__(self) -> None:
            self.stdout = _Stdout()
            self.terminated = False
            self.waited = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> None:
            self.waited = timeout is not None

    process = _Process()
    stop = threading.Event()

    with (
        patch("enshctl.lifecycle.gamelog.subprocess.Popen", return_value=process),
        caplog.at_level("INFO", logger="enshctl.lifecycle.gamelog"),
    ):
        # WHEN tailing the log
        gamelog.tail(tmp_path / "game.log", stop)
        stop.set()

    # THEN both lines are relayed and the tail process is stopped
    assert "one" in caplog.text
    assert "two" in caplog.text
    assert "2 lines relayed" in caplog.text
    assert process.terminated is True
    assert process.waited is True


def test_start_tail_stops_when_no_log_and_stop_is_set(tmp_path: Path) -> None:
    # GIVEN a stop event that is already set and no log file
    stop = threading.Event()
    stop.set()

    # WHEN starting the tail thread
    thread = gamelog.start_tail(stop, search_roots=(tmp_path,))
    thread.join(timeout=1)

    # THEN the thread returns without waiting for the search timeout
    assert thread.is_alive() is False
