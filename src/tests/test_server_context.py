"""Tests for ServerContext and signal handler integration."""

import subprocess
from subprocess import Popen
from typing import cast

import pytest
from enshctl.commands.start import ServerContext, _make_sigterm_handler


def test_server_context_init() -> None:
    ctx = ServerContext()
    assert ctx.server_process is None
    assert ctx.shutdown_requested is False


def test_server_context_state_isolation() -> None:
    ctx_a = ServerContext()
    ctx_b = ServerContext()

    ctx_a.shutdown_requested = True
    ctx_a.server_process = cast("Popen[bytes] | None", object())

    assert ctx_a.shutdown_requested is True
    assert ctx_b.shutdown_requested is False
    assert ctx_b.server_process is None


def test_sigterm_handler_sets_shutdown_flag() -> None:
    ctx = ServerContext()
    handler = _make_sigterm_handler(ctx)

    assert ctx.shutdown_requested is False
    with pytest.raises(SystemExit):
        handler(15, None)  # SIGTERM = 15
    assert ctx.shutdown_requested is True


def test_sigterm_handler_with_running_process() -> None:
    ctx = ServerContext()
    # Create a no-op mock process
    mock_proc = subprocess.Popen(["/usr/bin/sleep", "0"], stdout=subprocess.PIPE)
    mock_proc.wait()  # Ensure it exits immediately
    ctx.server_process = mock_proc

    handler = _make_sigterm_handler(ctx)
    with pytest.raises(SystemExit):
        handler(15, None)
    assert ctx.shutdown_requested is True
