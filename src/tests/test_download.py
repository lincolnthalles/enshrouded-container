"""Tests for download subcommand credential resolution."""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from enshctl.commands import download

if TYPE_CHECKING:
    import pytest


class TestDownloadCredentialResolution:
    """Tests for credential resolution priority: CLI > env vars > interactive."""

    @patch("enshctl.commands.download.install")
    @patch(
        "sys.argv",
        ["enshctl", "download", "999", "--steam-username", "cli_user", "--steam-password", "cli_pass"],
    )
    def test_cli_flags_override_env_vars(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI flags take precedence over environment variables."""
        monkeypatch.setenv("STEAM_USERNAME", "env_user")
        monkeypatch.setenv("STEAM_PASSWORD", "env_pass")
        download.run()
        mock_install.download_version.assert_called_once_with(
            "999",
            steam_username="cli_user",
            steam_password="cli_pass",
        )

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_env_vars_used_when_no_cli_flags(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables are used when no CLI flags provided."""
        monkeypatch.setenv("STEAM_USERNAME", "env_user")
        monkeypatch.setenv("STEAM_PASSWORD", "env_pass")
        download.run()
        mock_install.download_version.assert_called_once_with(
            "999",
            steam_username="env_user",
            steam_password="env_pass",
        )

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999"])
    def test_no_credentials_when_nothing_provided(
        self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No credentials passed when neither CLI flags nor env vars are set."""
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        download.run()
        mock_install.download_version.assert_called_once_with(
            "999",
            steam_username=None,
            steam_password=None,
        )

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-username", "cli_user"])
    def test_username_only_no_password(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only username passed when password not provided (DepotDownloader prompts interactively)."""
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        download.run()
        mock_install.download_version.assert_called_once_with(
            "999",
            steam_username="cli_user",
            steam_password=None,
        )

    @patch("enshctl.commands.download.install")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-password", "cli_pass"])
    def test_password_only_no_username(self, mock_install: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only password passed when username not provided (unusual but supported)."""
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        download.run()
        mock_install.download_version.assert_called_once_with(
            "999",
            steam_username=None,
            steam_password="cli_pass",
        )


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
        """Password value never appears in log output."""
        mock_download.return_value = MagicMock()
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        with caplog.at_level("DEBUG"):
            download.run()
        assert "secret123" not in caplog.text

    @patch.object(download.install, "download_version")
    @patch("sys.argv", ["enshctl", "download", "999", "--steam-username", "myuser"])
    def test_username_not_in_log_output(
        self, mock_download: MagicMock, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Username value never appears in log output."""
        mock_download.return_value = MagicMock()
        monkeypatch.delenv("STEAM_USERNAME", raising=False)
        monkeypatch.delenv("STEAM_PASSWORD", raising=False)
        with caplog.at_level("DEBUG"):
            download.run()
        assert "myuser" not in caplog.text
