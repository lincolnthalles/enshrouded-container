"""Tests for the CLI dispatcher's single exit."""

import pytest
from enshctl import __main__ as entrypoint
from enshctl.download.types import InstallError
from enshctl.settings import AppSettings


def test_main_exits_with_command_code(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a command that returns an exit code
    def command(_settings: AppSettings | None, _argv: list[str]) -> int:
        return 7

    monkeypatch.setattr("sys.argv", ["enshctl", "start"])
    monkeypatch.setattr(entrypoint, "COMMANDS", {"start": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint runs
    # THEN the process exits with that code
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 7


def test_main_passes_subcommand_argv_after_global_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a global flag before a subcommand with its own arguments
    received: list[str] = []

    def command(_settings: AppSettings | None, argv: list[str]) -> int:
        received.extend(argv)
        return 0

    monkeypatch.setattr(
        "sys.argv",
        ["enshctl", "--log-tail", "download", "999", "--steam-username", "user"],
    )
    monkeypatch.setattr(entrypoint, "COMMANDS", {"download": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint dispatches the command
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()

    # THEN only the subcommand arguments cross the dispatch seam
    assert exc_info.value.code == 0
    assert received == ["999", "--steam-username", "user"]


def test_main_merges_global_download_options(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a global API URL after the subcommand
    def command(settings: AppSettings | None, argv: list[str]) -> int:
        assert settings is not None
        assert settings.manifesthub_api_url == "https://mirror.example.com"
        assert settings.manifesthub_api_token == "token"
        assert settings.depot_keys_repo == "https://github.com/example/keys"
        assert argv == ["999"]
        return 0

    monkeypatch.setattr(
        "sys.argv",
        [
            "enshctl",
            "download",
            "999",
            "--api-url",
            "https://mirror.example.com/",
            "--api-token",
            "token",
            "--depot-keys-repo",
            "https://github.com/example/keys",
        ],
    )
    monkeypatch.setattr(entrypoint, "COMMANDS", {"download": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint dispatches the command
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()

    # THEN the global option is normalized into settings, not passed as argv
    assert exc_info.value.code == 0


def test_main_does_not_abbreviate_global_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a subcommand flag that is a prefix of a global flag
    received: list[str] = []

    def command(_settings: AppSettings | None, argv: list[str]) -> int:
        received.extend(argv)
        return 0

    monkeypatch.setattr("sys.argv", ["enshctl", "restore", "--l"])
    monkeypatch.setattr(entrypoint, "COMMANDS", {"restore": command})
    monkeypatch.setattr(entrypoint, "load_settings", AppSettings)

    # WHEN the entrypoint dispatches the command
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()

    # THEN the flag stays with the subcommand instead of becoming --log-tail
    assert exc_info.value.code == 0
    assert received == ["--l"]


def test_main_exits_one_on_fatal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a command that raises a dispatcher-handled error
    def command(_settings: AppSettings | None, _argv: list[str]) -> int:
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
    def command(_settings: AppSettings | None, _argv: list[str]) -> int:
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
    def command(_settings: AppSettings | None, _argv: list[str]) -> int:
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
