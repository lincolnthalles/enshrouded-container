"""Tests for the CLI dispatcher's single exit."""

import pytest
from enshctl import __main__ as entrypoint
from enshctl.download import InstallError
from enshctl.settings import AppSettings


def test_main_exits_with_command_code(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a command that returns an exit code
    def command(_settings: AppSettings | None) -> int:
        return 7

    monkeypatch.setattr("sys.argv", ["enshctl", "start"])
    monkeypatch.setattr(entrypoint, "COMMANDS", {"start": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint runs
    # THEN the process exits with that code
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 7


def test_main_exits_one_on_fatal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a command that raises a dispatcher-handled error
    def command(_settings: AppSettings | None) -> int:
        msg = "boom"
        raise OSError(msg)

    monkeypatch.setattr("sys.argv", ["enshctl", "start"])
    monkeypatch.setattr(entrypoint, "COMMANDS", {"start": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint runs
    # THEN the process exits 1
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 1


def test_main_propagates_command_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a command whose parser exits with a usage code
    def command(_settings: AppSettings | None) -> int:
        raise SystemExit(2)

    monkeypatch.setattr("sys.argv", ["enshctl", "start"])
    monkeypatch.setattr(entrypoint, "COMMANDS", {"start": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint runs
    # THEN the parser code becomes the process exit code
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2


def test_main_exits_one_on_install_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a command that leaks an Install error
    def command(_settings: AppSettings | None) -> int:
        msg = "install failed"
        raise InstallError(msg)

    monkeypatch.setattr("sys.argv", ["enshctl", "start"])
    monkeypatch.setattr(entrypoint, "COMMANDS", {"start": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint runs
    # THEN it logs and exits 1
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 1
