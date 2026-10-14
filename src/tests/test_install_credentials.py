"""Tests for install module Steam credential support."""

from dataclasses import replace
from unittest.mock import MagicMock, patch

from enshctl import install
from enshctl.settings import DEPOT_ID, AppSettings


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


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
        # GIVEN no credentials configured
        mock_run.return_value = MagicMock(returncode=0)
        target_dir = tmp_path / "manifests" / "999"
        target_dir.mkdir(parents=True)

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "sys"),
        ):
            # WHEN downloading anonymously
            install.download_version("999", _settings())

        # THEN no credential flags reach DepotDownloader
        call_args_list = [call[0][0] for call in mock_run.call_args_list]
        for cmd in call_args_list:
            if isinstance(cmd, list) and "/opt/depotdownloader/DepotDownloader" in cmd and "-validate" in cmd:
                assert "-username" not in cmd
                assert "-password" not in cmd
                assert "-remember-password" not in cmd

    @patch("enshctl.download.discover_depots", return_value=[(DEPOT_ID, "12345")])
    @patch("subprocess.run")
    def test_auth_free_preferred_when_keys_and_manifest_exist(
        self,
        mock_run: MagicMock,
        _mock_discover: MagicMock,
        tmp_path: MagicMock,
    ) -> None:
        # GIVEN depot.keys and a manifest file exist alongside configured Steam credentials
        mock_run.return_value = MagicMock(returncode=0)
        manifests_dir = tmp_path / "manifests"
        target_dir = manifests_dir / "999"
        target_dir.mkdir(parents=True)
        (manifests_dir / "depot.keys").write_bytes(b"2278521;deadbeef")
        manifest_file = manifests_dir / f"{DEPOT_ID}_999.manifest"
        manifest_file.write_bytes(b"manifest")

        with (
            patch.object(install, "MANIFESTS_DIR", manifests_dir),
            patch.object(install, "sys"),
            patch.object(install, "check_manifestfile_support", return_value=True),
        ):
            # WHEN downloading a non-latest version
            install.download_version(
                "999",
                _settings(version="999", steam_username="env_user", steam_password="env_pass"),
            )

        # THEN auth-free flags win over Steam credentials per the manifesthub spec
        call_args_list = [call[0][0] for call in mock_run.call_args_list]
        depot_cmd = None
        for cmd in call_args_list:
            if isinstance(cmd, list) and "/opt/depotdownloader/DepotDownloader" in cmd and "-validate" in cmd:
                depot_cmd = cmd
                break
        assert depot_cmd is not None
        assert "-manifestfile" in depot_cmd
        assert "-username" not in depot_cmd
        assert "-password" not in depot_cmd

    @patch("enshctl.download.discover_depots", return_value=[(DEPOT_ID, "12345")])
    @patch("subprocess.run")
    def test_authenticated_download_includes_credential_flags(
        self,
        mock_run: MagicMock,
        _mock_discover: MagicMock,
        tmp_path: MagicMock,
    ) -> None:
        # GIVEN explicit credentials
        mock_run.return_value = MagicMock(returncode=0)
        target_dir = tmp_path / "manifests" / "999"
        target_dir.mkdir(parents=True)

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "sys"),
        ):
            # WHEN downloading with credentials
            install.download_version(
                "999", _settings(version="999"), steam_username="testuser", steam_password="secret123"
            )

        # THEN credential flags reach DepotDownloader
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
        # GIVEN only a username
        mock_run.return_value = MagicMock(returncode=0)
        target_dir = tmp_path / "manifests" / "999"
        target_dir.mkdir(parents=True)

        with (
            patch.object(install, "MANIFESTS_DIR", tmp_path / "manifests"),
            patch.object(install, "sys"),
        ):
            # WHEN downloading with username only
            install.download_version("999", _settings(version="999"), steam_username="testuser")

        # THEN username flags appear without a password flag
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
