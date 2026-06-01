"""Tests for cmd subcommand registry."""

from collections.abc import Callable

from enshctl.commands import COMMANDS
from enshctl.commands.backup import run as backup_run
from enshctl.commands.debug_config import run as debug_config_run
from enshctl.commands.download import run as download_run
from enshctl.commands.install import run as install_run
from enshctl.commands.prune import run as prune_run
from enshctl.commands.restore import run as restore_run
from enshctl.commands.start import run as start_run
from enshctl.commands.verify import run as verify_run
from enshctl.commands.version_info import run as version_info_run


def test_registry_has_all_commands() -> None:
    expected = {
        "backup",
        "debug-config",
        "download",
        "install",
        "prune",
        "restore",
        "start",
        "verify",
        "version-info",
    }
    assert set(COMMANDS.keys()) == expected


def test_registry_values_are_callables() -> None:
    for name, func in COMMANDS.items():
        assert callable(func), f"{name} is not callable"
        assert isinstance(func, Callable)


def test_registry_maps_to_correct_functions() -> None:
    assert COMMANDS["backup"] is backup_run
    assert COMMANDS["debug-config"] is debug_config_run
    assert COMMANDS["download"] is download_run
    assert COMMANDS["install"] is install_run
    assert COMMANDS["prune"] is prune_run
    assert COMMANDS["restore"] is restore_run
    assert COMMANDS["start"] is start_run
    assert COMMANDS["verify"] is verify_run
    assert COMMANDS["version-info"] is version_info_run


def test_each_run_returns_none() -> None:
    for name, func in COMMANDS.items():
        assert func.__annotations__.get("return") is None, f"{name}.run() does not return None"
