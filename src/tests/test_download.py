"""Tests for download subcommand credential resolution."""

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.commands import download
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    import pytest


def _assert_download_call(mock_install: MagicMock, username: str | None, password: str | None) -> None:
    mock_install.download_version.assert_called_once()
    _args, kwargs = mock_install.download_version.call_args
    assert _args[0] == "999"
    assert kwargs["steam_username"] == username
    assert kwargs["steam_password"] == password


class TestDownloadCredentialResolution:
    """Tests for credential resolution priority: CLI > env vars > interactive."""

    @patch("enshctl.commands.download.install")
    @patch(
        "sys.argv",
        ["enshctl", "download", "999", "--steam-username", "cli_user", "--steam-password", "cli_pass"],
    )
    def test_cli_flags_override_env_vars(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIVEN credentials in both env and CLI flags
        monkeypatch.setenv("STEAM_USERNAME", "env_user")
        monkeypatch.setenv("STEAM_PASSWORD", "env_pass")
        # WHEN running the download command
        download.run()
        # THEN CLI flags win
        _assert_download_call(mock_install, "cli_user", "cli_pass")

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_env_vars_used_when_no_cli_flags(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIVEN credentials only in env
        monkeypatch.setenv("STEAM_USERNAME", "env_user")
        monkeypatch.setenv("STEAM_PASSWORD", "env_pass")
        # WHEN running the download command
        download.run()
        # THEN env values flow through
        _assert_download_call(mock_install, "env_user", "env_pass")

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_no_credentials_when_nothing_provided(
        self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # GIVEN no credentials anywhere
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        # WHEN running the download command
        download.run()
        # THEN no credentials pass through
        _assert_download_call(mock_install, None, None)

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-username", "cli_user"])
    def test_username_only_no_password(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIVEN only a CLI username
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        # WHEN running the download command
        download.run()
        # THEN username passes without a password
        _assert_download_call(mock_install, "cli_user", None)

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-password", "cli_pass"])
    def test_password_only_no_username(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIVEN only a CLI password
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        # WHEN running the download command
        download.run()
        # THEN password passes without a username
        _assert_download_call(mock_install, None, "cli_pass")

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_settings_object_carries_env_values(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIVEN env credentials and no CLI flags
        monkeypatch.setenv("STEAM_USERNAME", "env_user")
        monkeypatch.setenv("STEAM_PASSWORD", "env_pass")
        # WHEN running the download command
        download.run()
        # THEN the settings object passed to install matches env-derived values
        settings = mock_install.download_version.call_args[0][1]
        assert settings == replace(AppSettings(), steam_username="env_user", steam_password="env_pass")

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999", "--api-url", "https://mirror.example.com/"])
    def test_cli_api_url_trailing_slash_stripped(
        self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # GIVEN a CLI api-url with a trailing slash
        monkeypatch.delenv("MANIFESTHUB_API_URL", raising=False)
        # WHEN running the download command
        download.run()
        # THEN the stored URL is normalized like env-supplied values
        settings = mock_install.download_version.call_args[0][1]
        assert settings.manifesthub_api_url == "https://mirror.example.com"


class TestCredentialLoggingSafety:
    """Tests that credentials never appear in log output."""

    @patch.object(download.install, "download_version")
    @patch(
        "sys.argv",
        ["enshctl", "download", "999", "--steam-username", "myuser", "--steam-password", "secret123"],
    )
    def test_password_not_in_log_output(
        self, mock_download: MagicMock, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # GIVEN a CLI password
        mock_download.return_value = MagicMock()
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        # WHEN running with debug logging
        with caplog.at_level("DEBUG"):
            download.run()
        # THEN the password never appears in logs
        assert "secret123" not in caplog.text

    @patch.object(download.install, "download_version")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-username", "myuser"])
    def test_username_not_in_log_output(
        self, mock_download: MagicMock, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # GIVEN a CLI username
        mock_download.return_value = MagicMock()
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        # WHEN running with debug logging
        with caplog.at_level("DEBUG"):
            download.run()
        # THEN the username never appears in logs
        assert "myuser" not in caplog.text
