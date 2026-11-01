"""Tests for lifecycle process environment helpers."""

import signal
from dataclasses import replace
from typing import IO, TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from enshctl.lifecycle.process import make_tool_env, resolve_dll_overrides, signal_game, stream_output
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    import pytest
    from enshctl.lifecycle.types import ServerProcess


class TestMakeToolEnv:
    """Tests for make_tool_env() baseline wine tool environment."""

    def test_tool_env_has_baseline_video_and_dll_vars(self) -> None:
        # GIVEN default settings
        # WHEN building the wine tool environment
        env = make_tool_env(AppSettings())
        # THEN it carries the software-GL pin and the baseline DLL overrides
        assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
        assert env["WINEDLLOVERRIDES"] == "mscoree,mshtml="

    def test_tool_env_ignores_resolved_overrides(self) -> None:
        # GIVEN a user-provided WINEDLLOVERRIDES value
        settings = replace(AppSettings(), winedlloverrides="dinput8=n")
        # WHEN building the wine tool environment
        env = make_tool_env(settings)
        # THEN the baseline applies, not the per-run resolved value
        assert env["WINEDLLOVERRIDES"] == "mscoree,mshtml="


class TestResolveDllOverrides:
    """Tests for resolve_dll_overrides() user-provided value handling."""

    def test_empty_override_suppresses_generated(self) -> None:
        # GIVEN an explicitly empty WINEDLLOVERRIDES setting
        settings = replace(AppSettings(), winedlloverrides="")
        # WHEN resolving overrides from the settings object
        # THEN the empty value passes through verbatim instead of generated overrides
        assert resolve_dll_overrides(settings) == ""

    def test_unset_settings_value_generates(self) -> None:
        # GIVEN winedlloverrides unset
        settings = replace(AppSettings(), winedlloverrides=None)
        # WHEN resolving overrides
        # THEN generated overrides apply
        with patch(
            "enshctl.lifecycle.process.mods.generate_dll_overrides",
            return_value="mscoree,mshtml=,mylib=n",
        ):
            assert resolve_dll_overrides(settings) == "mscoree,mshtml=,mylib=n"

    def test_nonempty_settings_value_used_verbatim(self) -> None:
        # GIVEN winedlloverrides set to a custom value
        settings = replace(AppSettings(), winedlloverrides="dinput8=n")
        # WHEN resolving overrides
        # THEN the settings value wins verbatim over generation
        with patch(
            "enshctl.lifecycle.process.mods.generate_dll_overrides",
            side_effect=AssertionError("must not generate"),
        ):
            assert resolve_dll_overrides(settings) == "dinput8=n"


def test_signal_game_uses_pkill() -> None:
    # GIVEN a running game server
    with patch("enshctl.lifecycle.process.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # WHEN signaling the game
        delivered = signal_game(signal.SIGINT)
    # THEN pkill targets the game binary as steam
    assert delivered is True
    cmd = mock_run.call_args.args[0]
    assert cmd[:4] == ["/usr/bin/runuser", "-u", "steam", "--"]
    assert "enshrouded_server.exe" in cmd


def test_stream_output_drains_to_eof(caplog: pytest.LogCaptureFixture) -> None:
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
    with caplog.at_level("INFO", logger="enshctl.lifecycle.process"):
        thread = stream_output(cast("ServerProcess", process))
        thread.join(timeout=1)

    # THEN both lines are relayed and the stream is closed
    assert thread.is_alive() is False
    assert "one" in caplog.text
    assert "two" in caplog.text
    assert process.stdout.closed is True


def test_stream_output_handles_empty_stdout() -> None:
    # GIVEN a process without stdout
    class _Process:
        stdout: IO[bytes] | None = None

    # WHEN the reader starts
    thread = stream_output(cast("ServerProcess", _Process()))
    thread.join(timeout=1)

    # THEN it ends without raising
    assert thread.is_alive() is False
