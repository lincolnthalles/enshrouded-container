"""Tests for ServerContext and signal handler integration."""

import subprocess
from dataclasses import replace
from subprocess import Popen
from typing import cast
from unittest.mock import patch

import pytest
from enshctl.commands.start import ServerContext, _make_sigterm_handler, _resolve_dll_overrides
from enshctl.settings import AppSettings


def test_server_context_init() -> None:
    ctx = ServerContext()
    assert ctx.server_process is None
    assert ctx.shutdown_requested is False


def test_server_context_state_isolation() -> None:
    ctx_a = ServerContext()
    ctx_b = ServerContext()

    ctx_a.shutdown_requested = True
    ctx_a.server_process = cast("Popen[bytes] | None", object())

    assert ctx_b.shutdown_requested is False
    assert ctx_b.server_process is None


def test_sigterm_handler_sets_shutdown_flag() -> None:
    import threading

    ctx = ServerContext()
    handler = _make_sigterm_handler(ctx, AppSettings(), threading.Event())

    assert ctx.shutdown_requested is False
    with pytest.raises(SystemExit):
        handler(15, None)  # SIGTERM = 15


def test_sigterm_handler_with_running_process() -> None:
    import threading

    ctx = ServerContext()
    # Create a no-op mock process
    mock_proc = subprocess.Popen(["/usr/bin/sleep", "0"], stdout=subprocess.PIPE)
    mock_proc.wait()  # Ensure it exits immediately
    ctx.server_process = mock_proc

    handler = _make_sigterm_handler(ctx, AppSettings(), threading.Event())
    with pytest.raises(SystemExit):
        handler(15, None)
    assert ctx.shutdown_requested is True


class TestResolveDllOverrides:
    """Tests for _resolve_dll_overrides() user-provided value handling."""

    def test_empty_env_value_suppresses_generated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIVEN WINEDLLOVERRIDES set to an empty string in the environment
        monkeypatch.setenv("WINEDLLOVERRIDES", "")
        # WHEN resolving overrides from a freshly loaded settings object
        # THEN the empty value passes through verbatim instead of generated overrides
        assert _resolve_dll_overrides(AppSettings()) == ""

    def test_unset_settings_value_generates(self) -> None:
        # GIVEN winedlloverrides unset
        settings = replace(AppSettings(), winedlloverrides=None)
        # WHEN resolving overrides
        # THEN generated overrides apply
        with patch("enshctl.commands.start.mods.generate_dll_overrides", return_value="mscoree,mshtml=,mylib=n"):
            assert _resolve_dll_overrides(settings) == "mscoree,mshtml=,mylib=n"

    def test_nonempty_settings_value_used_verbatim(self) -> None:
        # GIVEN winedlloverrides set to a custom value
        settings = replace(AppSettings(), winedlloverrides="dinput8=n")
        # WHEN resolving overrides
        # THEN the settings value wins verbatim over generation
        with patch(
            "enshctl.commands.start.mods.generate_dll_overrides",
            side_effect=AssertionError("must not generate"),
        ):
            assert _resolve_dll_overrides(settings) == "dinput8=n"
