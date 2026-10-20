"""Tests for install module Steam credential support."""

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from enshctl import install
from enshctl.download import DownloadConfig
from enshctl.install import DownloadDeps, InstallEnv
from enshctl.settings import DEPOT_ID, AppSettings

if TYPE_CHECKING:
    from pathlib import Path


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


def test_download_config_carries_credentials() -> None:
    # GIVEN explicit credentials selected by the strategy
    config = DownloadConfig(username="testuser", password="secret123")

    # WHEN the config is inspected
    # THEN it carries both values
    assert config.username == "testuser"
    assert config.password == "secret123"


def test_username_only_config_has_no_password() -> None:
    # GIVEN username-only auth
    config = DownloadConfig(username="testuser")

    # WHEN the config is inspected
    # THEN no password travels with it
    assert config.username == "testuser"
    assert config.password is None


class TestDownloadVersionCredentials:
    """Tests for download_version() Steam credential flag composition."""

    def _manifests_dir(self, tmp_path: Path, *, with_keys: bool = False) -> Path:
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        if with_keys:
            (manifests_dir / "depot.keys").write_bytes(b"2278521;deadbeef")
            (manifests_dir / f"{DEPOT_ID}_999.manifest").write_bytes(b"manifest")
        return manifests_dir

    def _download(self, tmp_path: Path, settings: AppSettings, **overrides: object) -> DownloadConfig:
        with_keys = bool(overrides.pop("with_keys", False))
        manifests_dir = self._manifests_dir(tmp_path, with_keys=with_keys)
        captured: list[DownloadConfig] = []

        def _capture(mid: str, target: Path, config: DownloadConfig) -> None:
            captured.append(config)
            (target / "enshrouded_server.exe").write_bytes(b"")

        env = InstallEnv(
            disk_free=lambda _p: 12 * 1024**3,
            chown=lambda *_args, **_kwargs: None,
            chmod=lambda *_args, **_kwargs: MagicMock(returncode=0),
        )
        download = DownloadDeps(
            hub_download=lambda _a, _b, _c, _d, _e: manifests_dir / "existing.manifest",
            support=lambda: True,
            depot_download=_capture,
            discover=lambda: [(DEPOT_ID, "12345")],
        )
        from enshctl.install import DownloadAuth

        auth = DownloadAuth(
            username=overrides.pop("steam_username", None),  # type: ignore[arg-type]
            password=overrides.pop("steam_password", None),  # type: ignore[arg-type]
        )
        install.download_version(
            "999",
            settings,
            auth=auth,
            manifests_dir=manifests_dir,
            env=env,
            download=download,
            **overrides,  # type: ignore[arg-type]
        )
        assert captured
        return captured[0]

    def test_anonymous_download_no_credential_flags(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN no credentials configured
        from enshctl.download import _with_manifest_override

        assert _with_manifest_override([(DEPOT_ID, "12345")], "999") == [(DEPOT_ID, "999")]

        # WHEN downloading anonymously
        config = self._download(tmp_path, _settings())

        # THEN no credential flags reach DepotDownloader
        assert config.username is None
        assert config.password is None
        assert config.use_manifestfile is False

    def test_auth_free_used_when_no_username_and_keys_and_manifest_exist(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a manifest file exist with no Steam username configured
        # WHEN downloading a non-latest version
        config = self._download(tmp_path, _settings(version="999", steam_password="env_pass"), with_keys=True)

        # THEN auth-free flags are used per the manifesthub spec
        assert config.use_manifestfile is True
        assert config.username is None
        assert config.password is None

    def test_explicit_username_overrides_auth_free(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a manifest file exist alongside an explicit Steam username
        # WHEN downloading with an explicit username
        config = self._download(
            tmp_path,
            _settings(version="999", steam_username="env_user", steam_password="env_pass"),
            with_keys=True,
        )

        # THEN authenticated flags win over the auth-free path
        assert config.username == "env_user"
        assert config.use_manifestfile is False

    def test_authenticated_download_includes_credential_flags(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN explicit credentials
        # WHEN downloading with credentials
        config = self._download(
            tmp_path,
            _settings(version="999"),
            steam_username="testuser",
            steam_password="secret123",
        )

        # THEN credential flags reach DepotDownloader
        assert config.username == "testuser"
        assert config.password == "secret123"

    def test_username_only_no_password_flag(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN only a username
        # WHEN downloading with username only
        config = self._download(tmp_path, _settings(version="999"), steam_username="testuser")

        # THEN username is set without a password
        assert config.username == "testuser"
        assert config.password is None

    def test_latest_uses_auth_free_when_set_up(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a manifest file exist with VERSION=latest
        # WHEN downloading latest with auth-free set up
        config = self._download(tmp_path, _settings(), with_keys=True)

        # THEN the auth-free path is used
        assert config.use_manifestfile is True
        assert config.username is None

    def test_latest_falls_back_to_anonymous_with_no_credentials(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN no credentials, keys, or manifest with VERSION=latest
        # WHEN downloading latest with nothing configured
        config = self._download(tmp_path, _settings())

        # THEN the anonymous path is used (no auth flags, no QR)
        assert config.username is None
        assert config.use_manifestfile is False
        assert config.use_qr is False
