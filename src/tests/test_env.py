"""Tests for child-process environment policy."""

from enshctl.lifecycle.env import base_env


def test_base_env_keeps_only_allowlisted_keys() -> None:
    # GIVEN an inherited environment containing allowed and unrelated keys
    source = {
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "PUID": "1000",
        "GAME_ID": "730",
        "UNKNOWN": "leak",
    }

    # WHEN building the child environment
    # THEN only the allowlist crosses the process seam
    assert base_env(source) == {"PATH": "/usr/bin", "LANG": "C.UTF-8"}
