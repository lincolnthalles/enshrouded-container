"""Tests for install module Steam credential support."""

from unittest.mock import MagicMock, patch

from enshctl import install
from enshctl.settings import DEPOT_ID


class TestDownloadVersionCredentials:
    """Tests for download_version() Steam credential flag composition."""

    @patch("enshctl.download.discover_depots", return_value=[(DEPOT_ID, "12345")])
    @patch("subprocess.run")
    def test_anonymous_download_no_credential_flags(
        self,
        mock_run: MagicMock,
        _mock_discover: MagicMock,
        tmp_path: MagicMock,
    ) -> None:
        """download_version() without credentials invokes DepotDownloader without -username/-password."""
        mock_run.return_value = MagicMock(returncode=0)
        target_dir = tmp_path / "manifests" / "999"
        target_dir.mkdir(parents=True)

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "sys"),
        ):
            install.download_version("999")

        call_args_list = [call[0][0] for call in mock_run.call_args_list]
        for cmd in call_args_list:
            if isinstance(cmd, list) and "/opt/depotdownloader/DepotDownloader" in cmd and "-validate" in cmd:
                assert "-username" not in cmd
                assert "-password" not in cmd
                assert "-remember-password" not in cmd

    @patch("enshctl.download.discover_depots", return_value=[(DEPOT_ID, "12345")])
    @patch("subprocess.run")
    def test_authenticated_download_includes_credential_flags(
        self,
        mock_run: MagicMock,
        _mock_discover: MagicMock,
        tmp_path: MagicMock,
    ) -> None:
        """download_version() with credentials adds -username, -password, -remember-password."""
        mock_run.return_value = MagicMock(returncode=0)
        target_dir = tmp_path / "manifests" / "999"
        target_dir.mkdir(parents=True)

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "get_version", return_value="999"),
            patch.object(install, "sys"),
        ):
            install.download_version("999", steam_username="testuser", steam_password="secret123")

        call_args_list = [call[0][0] for call in mock_run.call_args_list]
        depot_cmd = None
        for cmd in call_args_list:
            if isinstance(cmd, list) and "/opt/depotdownloader/DepotDownloader" in cmd and "-validate" in cmd:
                depot_cmd = cmd
                break
        assert depot_cmd is not None
        assert "-username" in depot_cmd
        idx = depot_cmd.index("-username")
        assert depot_cmd[idx + 1] == "testuser"
        assert "-password" in depot_cmd
        idx = depot_cmd.index("-password")
        assert depot_cmd[idx + 1] == "secret123"
        assert "-remember-password" in depot_cmd

    @patch("enshctl.download.discover_depots", return_value=[(DEPOT_ID, "12345")])
    @patch("subprocess.run")
    def test_username_only_no_password_flag(
        self,
        mock_run: MagicMock,
        _mock_discover: MagicMock,
        tmp_path: MagicMock,
    ) -> None:
        """download_version() with only username adds -username and -remember-password but not -password."""
        mock_run.return_value = MagicMock(returncode=0)
        target_dir = tmp_path / "manifests" / "999"
        target_dir.mkdir(parents=True)

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "get_version", return_value="999"),
            patch.object(install, "sys"),
        ):
            install.download_version("999", steam_username="testuser")

        call_args_list = [call[0][0] for call in mock_run.call_args_list]
        depot_cmd = None
        for cmd in call_args_list:
            if isinstance(cmd, list) and "/opt/depotdownloader/DepotDownloader" in cmd and "-validate" in cmd:
                depot_cmd = cmd
                break
        assert depot_cmd is not None
        assert "-username" in depot_cmd
        assert "-password" not in depot_cmd
        assert "-remember-password" in depot_cmd
