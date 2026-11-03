"""Tests for shared subcommand argument parsing."""

from typing import TYPE_CHECKING

import pytest
from enshctl.commands import debug_config, install, start, version_info
from enshctl.commands.parser import CommandParser

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


def test_parser_parses_explicit_argv() -> None:
    # GIVEN a parser with a --file option
    parser = CommandParser("Test command")
    parser.add_argument("--file")

    # WHEN parsing explicit arguments
    args = parser.parse(["--file", "backup.tar.zst"])

    # THEN the namespace carries the parsed value
    assert args.file == "backup.tar.zst"


def test_parser_rejects_unknown_arguments() -> None:
    # GIVEN a parser with a --file option
    parser = CommandParser("Test command")
    parser.add_argument("--file")

    # WHEN an unknown flag is supplied
    with pytest.raises(SystemExit) as exc_info:
        parser.parse(["--unknown"])

    # THEN usage fails with argparse's code
    assert exc_info.value.code == 2


def test_parser_rejects_abbreviated_flags() -> None:
    # GIVEN a parser with a --file option
    parser = CommandParser("Test command")
    parser.add_argument("--file")

    # WHEN an abbreviated flag is supplied
    with pytest.raises(SystemExit) as exc_info:
        parser.parse(["--fi", "backup.tar.zst"])

    # THEN the parser rejects it rather than guessing
    assert exc_info.value.code == 2


@pytest.mark.parametrize("run", [start.run, install.run, version_info.run, debug_config.run])
def test_no_argument_commands_reject_unknown_argv(run: Callable[..., int]) -> None:
    # GIVEN a command with no subcommand arguments
    # WHEN an unknown flag reaches it
    with pytest.raises(SystemExit) as exc_info:
        run(argv=["--bogus"])

    # THEN strict parsing rejects it before any command work
    assert exc_info.value.code == 2


@pytest.mark.parametrize("command", [start, install])
def test_no_argument_commands_reject_before_loading_settings(
    command: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN a command whose settings load must not run
    monkeypatch.setattr(command, "load_settings", lambda: pytest.fail("settings loaded"))

    # WHEN an unknown flag reaches it
    with pytest.raises(SystemExit) as exc_info:
        command.run(argv=["--bogus"])

    # THEN parsing fails before settings are read
    assert exc_info.value.code == 2
