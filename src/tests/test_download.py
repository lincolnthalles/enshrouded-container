"""Tests for download subcommand credential resolution."""

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.commands import download
from enshctl.download.types import InstallError
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    import pytest


def _settings_with_credentials() -> AppSettings:
    return load_settings({"STEAM_USERNAME": "env_user", "STEAM_PASSWORD": "env_pass"})


def _assert_download_call(mock_flow: MagicMock, username: str | None, password: str | None) -> None:
    mock_flow.download_version.assert_called_once()
    args, kwargs = mock_flow.download_version.call_args
    assert args[0] == "999"
    settings = args[1]
    assert settings.steam_username == username
    assert settings.steam_password == password
    assert kwargs["version_spec"] == "999"


class TestDownloadCredentialResolution:
    """Tests for credential resolution priority: CLI > settings > interactive."""

    @patch("enshctl.commands.download.download_flow")
    @patch(
        "sys.argv",
        ["enshctl", "download", "999", "--steam-username", "cli_user", "--steam-password", "cli_pass"],
    )
    def test_cli_flags_override_settings(self, mock_flow: MagicMock) -> None:
        # GIVEN credentials in both settings and CLI flags
        # WHEN running the download command
        download.run(_settings_with_credentials())
        # THEN CLI flags win
        _assert_download_call(mock_flow, "cli_user", "cli_pass")

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_settings_credentials_used_when_no_cli_flags(self, mock_flow: MagicMock) -> None:
        # GIVEN credentials only in settings
        # WHEN running the download command
        download.run(_settings_with_credentials())
        # THEN the settings credentials pass through
        _assert_download_call(mock_flow, "env_user", "env_pass")

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_no_credentials_when_nothing_provided(self, mock_flow: MagicMock) -> None:
        # GIVEN settings with no credentials
        # WHEN running the download command
        download.run(load_settings({}))
        # THEN no credentials pass through
        _assert_download_call(mock_flow, None, None)

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "abc"])
    def test_invalid_manifest_id_rejected_before_prepare(self, mock_flow: MagicMock) -> None:
        # GIVEN a non-numeric Manifest ID
        mock_flow.validate_manifest_id.side_effect = InstallError("Invalid Manifest ID")

        # WHEN running the download command
        code = download.run(load_settings({}))

        # THEN it returns 1 before auth-free setup or download
        assert code == 1
        mock_flow.prepare_manifests.assert_not_called()
        mock_flow.download_version.assert_not_called()

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-username", "cli_user"])
    def test_username_only_no_password(self, mock_flow: MagicMock) -> None:
        # GIVEN only a CLI username
        # WHEN running the download command
        download.run(load_settings({}))
        # THEN username passes without a password
        _assert_download_call(mock_flow, "cli_user", None)

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-password", "cli_pass"])
    def test_password_only_no_username(self, mock_flow: MagicMock) -> None:
        # GIVEN only a CLI password
        # WHEN running the download command
        download.run(load_settings({}))
        # THEN password passes without a username
        _assert_download_call(mock_flow, None, "cli_pass")

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_settings_object_carries_credentials(self, mock_flow: MagicMock) -> None:
        # GIVEN settings loaded from env values and no CLI flags
        # WHEN running the download command
        download.run(_settings_with_credentials())
        # THEN the settings object passed to download matches the env-derived values
        settings = mock_flow.download_version.call_args[0][1]
        assert settings == replace(AppSettings(), steam_username="env_user", steam_password="env_pass")

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_command_loads_settings_when_none_injected(self, mock_flow: MagicMock) -> None:
        # GIVEN no injected settings object
        # WHEN running the download command
        with patch("enshctl.commands.download.load_settings", return_value=_settings_with_credentials()):
            download.run()
        # THEN the command loads settings and uses their credentials
        _assert_download_call(mock_flow, "env_user", "env_pass")

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999", "--api-url", "https://mirror.example.com/"])
    def test_cli_api_url_trailing_slash_stripped(self, mock_flow: MagicMock) -> None:
        # GIVEN a CLI api-url with a trailing slash
        # WHEN running the download command
        download.run(load_settings({}))
        # THEN the stored URL is normalized like env-supplied values
        settings = mock_flow.download_version.call_args[0][1]
        assert settings.manifesthub_api_url == "https://mirror.example.com"


class TestCredentialLoggingSafety:
    """Tests that credentials never appear in log output."""

    @patch("enshctl.commands.download.download_flow")
    @patch(
        "sys.argv",
        ["enshctl", "download", "999", "--steam-username", "myuser", "--steam-password", "secret123"],
    )
    def test_password_not_in_log_output(self, mock_flow: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        # GIVEN a CLI password
        mock_flow.download_version.return_value = MagicMock()
        # WHEN running with debug logging
        with caplog.at_level("DEBUG"):
            download.run(load_settings({}))
        # THEN the password never appears in logs
        assert "secret123" not in caplog.text

    @patch("enshctl.commands.download.download_flow")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-username", "myuser"])
    def test_username_not_in_log_output(self, mock_flow: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        # GIVEN a CLI username
        mock_flow.download_version.return_value = MagicMock()
        # WHEN running with debug logging
        with caplog.at_level("DEBUG"):
            download.run(load_settings({}))
        # THEN the username never appears in logs
        assert "myuser" not in caplog.text
