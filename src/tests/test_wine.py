"""Tests for Wine environment policy and prefix lifecycle."""

import subprocess
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from enshctl.lifecycle import wine
from enshctl.paths import WINE_PREFIX
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path


def test_tool_env_builds_full_environment() -> None:
    # GIVEN explicit settings and a controlled inherited environment
    settings = replace(
        AppSettings(),
        winearch="win64",
        winedebug="-all",
        home="/home/steam",
        puid=1234,
        winedlloverrides="dinput8=n",
    )

    # WHEN building the wine tool environment
    env = wine.tool_env(settings, source={"PATH": "/usr/bin", "TZ": "UTC"})

    # THEN it carries the allowlisted base variables, baseline overrides, and wine settings
    assert env == {
        "PATH": "/usr/bin",
        "TZ": "UTC",
        "WINEPREFIX": str(WINE_PREFIX),
        "WINEARCH": "win64",
        "WINEDEBUG": "-all",
        "HOME": "/home/steam",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "WINEDLLOVERRIDES": "mscoree,mshtml=",
        "XDG_RUNTIME_DIR": "/var/run/user/1234",
    }


def test_tool_env_ignores_resolved_overrides() -> None:
    # GIVEN a user-provided WINEDLLOVERRIDES value
    settings = replace(AppSettings(), winedlloverrides="dinput8=n")
    # WHEN building the wine tool environment
    env = wine.tool_env(settings, source={})
    # THEN the baseline applies, not the per-run resolved value
    assert env["WINEDLLOVERRIDES"] == "mscoree,mshtml="


def test_server_env_uses_resolved_overrides() -> None:
    # GIVEN a user-provided WINEDLLOVERRIDES value
    settings = replace(
        AppSettings(),
        winearch="win64",
        winedebug="-all",
        home="/home/steam",
        puid=1234,
        winedlloverrides="dinput8=n",
    )

    # WHEN building the game-server environment
    env = wine.server_env(settings, source={"PATH": "/usr/bin"})

    # THEN the resolved value applies to the full environment
    assert env == {
        "PATH": "/usr/bin",
        "WINEPREFIX": str(WINE_PREFIX),
        "WINEARCH": "win64",
        "WINEDEBUG": "-all",
        "HOME": "/home/steam",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "WINEDLLOVERRIDES": "dinput8=n",
        "XDG_RUNTIME_DIR": "/var/run/user/1234",
    }


def test_ensure_prefix_skips_when_marker_exists(tmp_path: Path) -> None:
    # GIVEN an initialized prefix marker
    marker = tmp_path / "prefix.initialized"
    marker.touch()

    with patch("enshctl.lifecycle.wine.subprocess.run") as mock_run:
        # WHEN ensuring the prefix
        wine.ensure_prefix(
            AppSettings(),
            marker_path=marker,
            wineserver_path=tmp_path / "missing-wineserver",
        )

    # THEN no cleanup or initialization subprocess runs
    mock_run.assert_not_called()


def test_ensure_prefix_cleans_then_initializes(tmp_path: Path) -> None:
    # GIVEN no prefix marker and an available wineserver binary
    marker = tmp_path / "prefix.initialized"
    wineserver = tmp_path / "wineserver"
    wineserver.touch()

    with patch("enshctl.lifecycle.wine.subprocess.run") as mock_run:
        # WHEN ensuring the prefix
        wine.ensure_prefix(AppSettings(), marker_path=marker, wineserver_path=wineserver)

    # THEN cleanup runs before wineboot and the completion marker is written
    assert marker.exists()
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0].args[0] == ["/usr/bin/runuser", "-u", "steam", "--", str(wineserver), "-k"]
    assert mock_run.call_args_list[1].args[0] == [
        "/usr/bin/runuser",
        "-u",
        "steam",
        "--",
        "xvfb-run",
        "--auto-servernum",
        "wine",
        "wineboot",
        "--init",
    ]
    assert mock_run.call_args_list[1].kwargs["check"] is True
    assert mock_run.call_args_list[1].kwargs["env"]["WINEDLLOVERRIDES"] == "mscoree,mshtml="


def test_ensure_prefix_propagates_initialization_failure(tmp_path: Path) -> None:
    # GIVEN a prefix initialization that fails
    marker = tmp_path / "prefix.initialized"
    error = subprocess.CalledProcessError(1, ["wineboot", "--init"])

    with (
        patch("enshctl.lifecycle.wine.subprocess.run", side_effect=error),
        pytest.raises(subprocess.CalledProcessError),
    ):
        # WHEN ensuring the prefix
        wine.ensure_prefix(
            AppSettings(),
            marker_path=marker,
            wineserver_path=tmp_path / "missing-wineserver",
        )

    # THEN the failure propagates and no completion marker is written
    assert not marker.exists()


def test_ensure_prefix_propagates_initialization_timeout(tmp_path: Path) -> None:
    # GIVEN a prefix initialization that times out
    marker = tmp_path / "prefix.initialized"
    timeout = subprocess.TimeoutExpired(["wineboot", "--init"], 60)

    with (
        patch("enshctl.lifecycle.wine.subprocess.run", side_effect=timeout),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        # WHEN ensuring the prefix
        wine.ensure_prefix(
            AppSettings(),
            marker_path=marker,
            wineserver_path=tmp_path / "missing-wineserver",
        )

    # THEN the timeout propagates and no completion marker is written
    assert not marker.exists()


def test_cleanup_runs_graceful_shutdown(tmp_path: Path) -> None:
    # GIVEN an available wineserver binary
    wineserver = tmp_path / "wineserver"
    wineserver.touch()

    with patch("enshctl.lifecycle.wine.subprocess.run") as mock_run:
        # WHEN cleaning up the Wine server
        wine.cleanup(AppSettings(), wineserver_path=wineserver)

    # THEN the graceful shutdown runs once
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == ["/usr/bin/runuser", "-u", "steam", "--", str(wineserver), "-k"]
    assert mock_run.call_args.kwargs["check"] is False
    assert mock_run.call_args.kwargs["timeout"] == 10


def test_cleanup_escalates_to_k9_on_timeout(tmp_path: Path) -> None:
    # GIVEN a wineserver whose graceful shutdown times out
    wineserver = tmp_path / "wineserver"
    wineserver.touch()
    timeout = subprocess.TimeoutExpired(["wineserver", "-k"], 10)

    with patch("enshctl.lifecycle.wine.subprocess.run", side_effect=[timeout, MagicMock()]) as mock_run:
        # WHEN cleaning up the Wine server
        wine.cleanup(AppSettings(), wineserver_path=wineserver)

    # THEN it retries with the forced flag under the baseline tool environment
    assert mock_run.call_count == 2
    first = mock_run.call_args_list[0]
    second = mock_run.call_args_list[1]
    assert first.args[0] == ["/usr/bin/runuser", "-u", "steam", "--", str(wineserver), "-k"]
    assert second.args[0] == ["/usr/bin/runuser", "-u", "steam", "--", str(wineserver), "-k9"]
    assert first.kwargs["env"]["WINEDLLOVERRIDES"] == "mscoree,mshtml="
    assert second.kwargs["env"]["WINEDLLOVERRIDES"] == "mscoree,mshtml="


def test_cleanup_warns_when_forced_cleanup_also_times_out(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN both graceful and forced shutdowns time out
    wineserver = tmp_path / "wineserver"
    wineserver.touch()
    timeout = subprocess.TimeoutExpired(["wineserver", "-k"], 10)

    with (
        patch("enshctl.lifecycle.wine.subprocess.run", side_effect=[timeout, timeout]),
        caplog.at_level("WARNING", logger="enshctl.lifecycle.wine"),
    ):
        # WHEN cleaning up the Wine server
        wine.cleanup(AppSettings(), wineserver_path=wineserver)

    # THEN the forced timeout is reported without raising
    assert "Forced Wine server cleanup also timed out" in caplog.text


def test_cleanup_skips_when_binary_is_missing(tmp_path: Path) -> None:
    with patch("enshctl.lifecycle.wine.subprocess.run") as mock_run:
        # WHEN the wineserver binary is absent
        wine.cleanup(AppSettings(), wineserver_path=tmp_path / "missing-wineserver")

    # THEN no cleanup subprocess runs
    mock_run.assert_not_called()
