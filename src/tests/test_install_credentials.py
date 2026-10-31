"""Tests for download flow strategy composition."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest
from enshctl.disk_space import SpaceGuard
from enshctl.download import (
    DownloadConfig,
    DownloadIO,
    HostIO,
    InstallError,
    download_version,
    prepare_manifests,
)
from enshctl.paths import DEPOT_ID
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from collections.abc import Callable


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


def _host(free: int = 12 * 1024**3) -> MagicMock:
    host = MagicMock(spec=HostIO)
    host.space = SpaceGuard(disk_free=lambda _p: free)
    host.is_file.side_effect = Path.is_file
    host.is_symlink.side_effect = Path.is_symlink
    host.mkdir.side_effect = lambda path: path.mkdir(parents=True, exist_ok=True)
    host.touch.side_effect = Path.touch
    return host


def _download() -> MagicMock:
    download = MagicMock(spec=DownloadIO)
    download.check_manifest_support.return_value = True
    download.discover_depots.return_value = [(DEPOT_ID, "12345")]

    def _write_exe(_mid: str, target: Path, _config: object, _pinned: object = None) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / "enshrouded_server.exe").write_bytes(b"")

    download.download_depots.side_effect = _write_exe
    return download


def _manifests_dir(tmp_path: Path, *, with_keys: bool = False, with_manifest: bool = False) -> Path:
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    if with_keys:
        (manifests_dir / "depot.keys").write_bytes(b"2278521;deadbeef")
    if with_manifest:
        (manifests_dir / f"{DEPOT_ID}_999.manifest").write_bytes(b"manifest")
    return manifests_dir


def _write_manifest(depot_id: str, manifest_id: str, output_dir: Path, _api_key: str, _api_url: str) -> Path:
    path = output_dir / f"{depot_id}_{manifest_id}.manifest"
    path.write_bytes(b"manifest")
    return path


def _auth_free_config(manifests_dir: Path) -> DownloadConfig:
    return DownloadConfig(
        use_manifestfile=True,
        manifest_file=manifests_dir / f"{DEPOT_ID}_999.manifest",
        depot_keys_path=manifests_dir / "depot.keys",
    )


def _capture_config(download: MagicMock) -> DownloadConfig:
    assert download.download_depots.call_count == 1
    return cast("DownloadConfig", download.download_depots.call_args.args[2])


class TestDownloadVersionCredentials:
    """Tests for download_version() Steam credential flag composition."""

    def _config(
        self,
        tmp_path: Path,
        settings: AppSettings,
        *,
        with_keys: bool = False,
        with_manifest: bool = False,
        version_spec: str | None = None,
        configure: Callable[[MagicMock], None] | None = None,
    ) -> tuple[DownloadConfig, MagicMock]:
        manifests_dir = _manifests_dir(tmp_path, with_keys=with_keys, with_manifest=with_manifest)
        host = _host()
        download = _download()
        if configure is not None:
            configure(download)
        download_version(
            "999",
            settings,
            manifests_dir=manifests_dir,
            version_spec=version_spec,
            host=cast("HostIO", host),
            source=cast("DownloadIO", download),
        )
        return _capture_config(download), download

    def test_anonymous_download_no_credential_flags(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN no credentials configured
        # WHEN downloading anonymously
        config, _ = self._config(tmp_path, _settings())

        # THEN the anonymous strategy is used
        assert config == DownloadConfig()

    def test_auth_free_used_when_no_username_and_keys_and_manifest_exist(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a Manifest file exist with no Steam username configured
        # WHEN downloading a non-latest version
        config, _ = self._config(
            tmp_path,
            _settings(version="999", steam_password="env_pass"),
            with_keys=True,
            with_manifest=True,
        )

        # THEN auth-free flags are used per the manifesthub spec
        assert config == _auth_free_config(tmp_path / "manifests")

    def test_explicit_username_overrides_auth_free(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a Manifest file exist alongside an explicit Steam username
        # WHEN downloading with an explicit username
        config, _ = self._config(
            tmp_path,
            _settings(version="999", steam_username="env_user", steam_password="env_pass"),
            with_keys=True,
            with_manifest=True,
        )

        # THEN authenticated flags win over the auth-free path
        assert config == DownloadConfig(username="env_user", password="env_pass")

    def test_authenticated_download_includes_credential_flags(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN explicit credentials
        # WHEN downloading with credentials
        config, _ = self._config(
            tmp_path,
            _settings(version="999", steam_username="testuser", steam_password="secret123"),
        )

        # THEN credential flags reach DepotDownloader
        assert config == DownloadConfig(username="testuser", password="secret123")

    def test_username_only_no_password_flag(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN only a username
        # WHEN downloading with username only
        config, _ = self._config(tmp_path, _settings(version="999", steam_username="testuser"))

        # THEN username is set without a password
        assert config == DownloadConfig(username="testuser")

    def test_latest_uses_auth_free_when_set_up(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a Manifest file exist with VERSION=latest
        # WHEN downloading latest with auth-free set up
        config, _ = self._config(tmp_path, _settings(), with_keys=True, with_manifest=True)

        # THEN the auth-free path is used
        assert config == _auth_free_config(tmp_path / "manifests")

    def test_latest_falls_back_to_anonymous_with_no_credentials(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN no credentials, keys, or Manifest with VERSION=latest
        # WHEN downloading latest with nothing configured
        config, _ = self._config(tmp_path, _settings())

        # THEN the anonymous path is used
        assert config == DownloadConfig()

    def test_empty_version_uses_anonymous(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN an empty Version spec, which resolves as latest
        # WHEN downloading with nothing configured
        config, _ = self._config(tmp_path, _settings(version=""))

        # THEN the anonymous path is used
        assert config == DownloadConfig()

    def test_explicit_manifest_id_uses_qr_with_latest_settings(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN VERSION=latest but an explicit Manifest ID selected by the CLI
        # WHEN downloading without Manifest material or credentials
        config, _ = self._config(tmp_path, _settings(), version_spec="999")

        # THEN the explicit ID uses QR instead of anonymous
        assert config == DownloadConfig(use_qr=True, print_qr_message=True)

    def test_multi_depot_download_runs_single_pass_with_pin(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN two depots discovered with their own Manifest IDs
        # WHEN downloading a pinned Manifest ID
        manifests_dir = _manifests_dir(tmp_path)
        host = _host()
        download = _download()
        download.discover_depots.return_value = [("2278521", "111"), ("2278522", "222")]

        download_version(
            "999",
            _settings(version="999"),
            manifests_dir=manifests_dir,
            host=cast("HostIO", host),
            source=cast("DownloadIO", download),
        )

        # THEN depot download runs once with the pin applied to the target depot only
        assert download.download_depots.call_args.args[3] == [("2278521", "999"), ("2278522", "222")]

    def test_empty_discovery_falls_back_to_default_depot(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN discovery reports no depots
        manifests_dir = _manifests_dir(tmp_path)
        host = _host()
        download = _download()
        no_depots: list[tuple[str, str]] = []
        download.discover_depots.return_value = no_depots

        # WHEN downloading
        download_version(
            "999",
            _settings(version="999"),
            manifests_dir=manifests_dir,
            host=cast("HostIO", host),
            source=cast("DownloadIO", download),
        )

        # THEN the default depot is downloaded with the pinned Manifest
        assert download.download_depots.call_args.args[3] == [(DEPOT_ID, "999")]

    def test_no_support_with_material_fails_with_mod_fork_guidance(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a Manifest file but no DepotDownloader support and no Steam username
        manifests_dir = _manifests_dir(tmp_path, with_keys=True, with_manifest=True)
        host = _host()
        download = _download()
        download.check_manifest_support.return_value = False

        # WHEN downloading without Steam credentials
        with pytest.raises(InstallError, match="Mod fork"):
            download_version(
                "999",
                _settings(version="999", steam_username=None, steam_password=None, min_free_space=0),
                manifests_dir=manifests_dir,
                host=cast("HostIO", host),
                source=cast("DownloadIO", download),
            )

        # THEN the install fails before any depot download
        download.download_depots.assert_not_called()

    def test_no_support_with_material_fails_for_latest_version(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN depot.keys and a Manifest file but no DepotDownloader support and no Steam username
        manifests_dir = _manifests_dir(tmp_path, with_keys=True, with_manifest=True)
        host = _host()
        download = _download()
        download.check_manifest_support.return_value = False

        # WHEN downloading with the Version spec set to latest
        with pytest.raises(InstallError, match="Mod fork"):
            download_version(
                "999",
                _settings(version="latest", steam_username=None, steam_password=None, min_free_space=0),
                manifests_dir=manifests_dir,
                host=cast("HostIO", host),
                source=cast("DownloadIO", download),
            )

        # THEN the install still fails instead of falling through to anonymous download
        download.download_depots.assert_not_called()

    def test_manifest_without_keys_and_no_username_fails(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a Manifest file without depot keys and no Steam username
        manifests_dir = _manifests_dir(tmp_path, with_manifest=True)
        host = _host()
        download = _download()

        # WHEN downloading
        # THEN the install fails naming key setup and Steam login
        with pytest.raises(InstallError, match=r"no depot\.keys"):
            download_version(
                "999",
                _settings(version="999", min_free_space=0),
                manifests_dir=manifests_dir,
                host=cast("HostIO", host),
                source=cast("DownloadIO", download),
            )
        download.download_depots.assert_not_called()

    def test_manifest_without_keys_and_username_uses_steam(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a Manifest file without depot keys but with a Steam username
        # WHEN downloading
        config, _ = self._config(
            tmp_path,
            _settings(version="999", steam_username="testuser"),
            with_manifest=True,
        )

        # THEN Steam auth wins over the missing keys
        assert config == DownloadConfig(username="testuser")

    def test_manifest_fetch_failure_is_carried_to_strategy(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # GIVEN a ManifestHub token and URL with no local Manifest file
        host = _host()
        download = _download()
        download.download_manifest.side_effect = InstallError("hub down")
        settings = _settings(
            version="999",
            manifesthub_api_token="token",
            manifesthub_api_url="https://hub.example",
            min_free_space=0,
        )

        # WHEN the fetch fails and the flow falls through to QR login
        with caplog.at_level("WARNING", logger="enshctl.download.flow"):
            download_version(
                "999",
                settings,
                manifests_dir=_manifests_dir(tmp_path),
                host=cast("HostIO", host),
                source=cast("DownloadIO", download),
            )

        # THEN the failure is carried to the decision point and logged, not swallowed
        assert any("hub down" in record.message for record in caplog.records)
        assert any("Proceeding with QR login" in record.message for record in caplog.records)
        assert _capture_config(download) == DownloadConfig(use_qr=True, print_qr_message=True)

    def test_manifest_fetch_failure_does_not_block_steam(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a ManifestHub failure and a Steam username
        download = _download()
        download.download_manifest.side_effect = InstallError("hub down")
        settings = _settings(
            version="999",
            steam_username="testuser",
            manifesthub_api_token="token",
            manifesthub_api_url="https://hub.example",
            min_free_space=0,
        )

        # WHEN the fetch fails
        download_version(
            "999",
            settings,
            manifests_dir=_manifests_dir(tmp_path),
            host=cast("HostIO", _host()),
            source=cast("DownloadIO", download),
        )

        # THEN the Steam strategy still proceeds
        assert _capture_config(download) == DownloadConfig(username="testuser")

    def test_manifest_fetch_success_allows_auth_free(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a ManifestHub token and URL with depot keys but no local Manifest file
        download = _download()
        download.download_manifest.side_effect = _write_manifest
        settings = _settings(
            version="999",
            manifesthub_api_token="token",
            manifesthub_api_url="https://hub.example",
            min_free_space=0,
        )

        # WHEN the fetch succeeds
        download_version(
            "999",
            settings,
            manifests_dir=_manifests_dir(tmp_path, with_keys=True),
            host=cast("HostIO", _host()),
            source=cast("DownloadIO", download),
        )

        # THEN the auth-free strategy uses the acquired Manifest file
        assert (tmp_path / "manifests" / f"{DEPOT_ID}_999.manifest").is_file()
        assert _capture_config(download) == _auth_free_config(tmp_path / "manifests")

    def test_manifest_fetch_without_file_is_carried(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # GIVEN a ManifestHub token and URL whose download produces no file
        manifests_dir = _manifests_dir(tmp_path)
        download = _download()
        download.download_manifest.return_value = manifests_dir / f"{DEPOT_ID}_999.manifest"
        settings = _settings(
            version="999",
            manifesthub_api_token="token",
            manifesthub_api_url="https://hub.example",
            min_free_space=0,
        )

        # WHEN the flow checks the acquired Manifest
        with caplog.at_level("WARNING", logger="enshctl.download.flow"):
            download_version(
                "999",
                settings,
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host()),
                source=cast("DownloadIO", download),
            )

        # THEN the missing result is carried and logged
        assert any("did not produce" in record.message for record in caplog.records)

    def test_present_manifest_skips_hub_fetch(
        self,
        tmp_path: Path,
    ) -> None:
        # GIVEN a local Manifest file, depot keys, and a ManifestHub token
        settings = _settings(
            version="999",
            manifesthub_api_token="token",
            manifesthub_api_url="https://hub.example",
            min_free_space=0,
        )

        # WHEN downloading
        config, download = self._config(
            tmp_path,
            settings,
            with_keys=True,
            with_manifest=True,
        )

        # THEN no ManifestHub fetch runs and auth-free is used
        download.download_manifest.assert_not_called()
        assert config == _auth_free_config(tmp_path / "manifests")

    def test_invalid_manifest_id_rejected(self, tmp_path: Path) -> None:
        # GIVEN a non-numeric Manifest ID
        # WHEN downloading
        # THEN the install fails before using it as a path
        with pytest.raises(InstallError, match="Invalid Manifest ID"):
            download_version(
                "../escape",
                _settings(min_free_space=0),
                manifests_dir=tmp_path / "manifests",
                host=cast("HostIO", _host()),
                source=cast("DownloadIO", _download()),
            )

    def test_symlinked_install_dir_rejected(self, tmp_path: Path) -> None:
        # GIVEN a Manifest install directory that is a symlink outside the tree
        manifests_dir = _manifests_dir(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep").write_bytes(b"keep")
        (manifests_dir / "999").symlink_to(outside, target_is_directory=True)
        download = _download()

        # WHEN downloading
        # THEN the install refuses to follow it
        with pytest.raises(InstallError, match="symlinked Manifest install directory"):
            download_version(
                "999",
                _settings(version="999", force_install=True, min_free_space=0),
                manifests_dir=manifests_dir,
                host=cast("HostIO", _host()),
                source=cast("DownloadIO", download),
            )
        download.download_depots.assert_not_called()
        assert (outside / "keep").read_bytes() == b"keep"

    def test_manifest_fetch_failure_does_not_abort_latest(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # GIVEN a ManifestHub failure with VERSION=latest
        download = _download()
        download.download_manifest.side_effect = InstallError("hub down")
        settings = _settings(
            version="latest",
            manifesthub_api_token="token",
            manifesthub_api_url="https://hub.example",
            min_free_space=0,
        )

        # WHEN the fetch fails
        with caplog.at_level("WARNING", logger="enshctl.download.flow"):
            download_version(
                "999",
                settings,
                manifests_dir=_manifests_dir(tmp_path),
                host=cast("HostIO", _host()),
                source=cast("DownloadIO", download),
            )

        # THEN anonymous download still proceeds with the failure logged
        assert _capture_config(download) == DownloadConfig()
        assert any("Proceeding with anonymous" in record.message for record in caplog.records)


def test_prepare_manifests_fetches_keys_without_token(tmp_path: Path) -> None:
    # GIVEN a depot keys repo but no ManifestHub token
    manifests_dir = _manifests_dir(tmp_path)
    settings = _settings(depot_keys_repo="https://github.com/example/keys")
    download = _download()

    # WHEN running auth-free setup
    prepare_manifests(settings, manifests_dir=manifests_dir, source=cast("DownloadIO", download))

    # THEN keys are fetched from the repo without requiring a token
    download.ensure_depot_keys.assert_called_once_with(manifests_dir, "https://github.com/example/keys")


def test_prepare_manifests_fetches_missing_manifests(tmp_path: Path) -> None:
    # GIVEN a ManifestHub token and URL with a non-empty listing
    manifests_dir = _manifests_dir(tmp_path)
    settings = _settings(
        manifesthub_api_token="token",
        manifesthub_api_url="https://hub.example",
    )
    download = _download()
    download.list_manifests.return_value = ["1", "2"]

    # WHEN running auth-free setup
    prepare_manifests(settings, manifests_dir=manifests_dir, source=cast("DownloadIO", download))

    # THEN every missing Manifest is prefetched
    download.fetch_missing_manifests.assert_called_once_with(["1", "2"], manifests_dir, "token", "https://hub.example")


def test_prepare_manifests_empty_listing_skips(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a ManifestHub token and URL with an empty listing
    manifests_dir = _manifests_dir(tmp_path)
    settings = _settings(
        manifesthub_api_token="token",
        manifesthub_api_url="https://hub.example",
    )
    download = _download()
    empty: list[str] = []
    download.list_manifests.return_value = empty

    # WHEN running auth-free setup
    with caplog.at_level("WARNING", logger="enshctl.download.flow"):
        prepare_manifests(settings, manifests_dir=manifests_dir, source=cast("DownloadIO", download))

    # THEN prefetching is skipped with a warning
    download.fetch_missing_manifests.assert_not_called()
    assert any("No manifests discovered" in record.message for record in caplog.records)


def test_prepare_manifests_token_without_url_fails(tmp_path: Path) -> None:
    # GIVEN a ManifestHub token without a URL
    settings = _settings(manifesthub_api_token="token")
    download = _download()

    # WHEN running auth-free setup
    # THEN the Install fails before probing or fetching
    with pytest.raises(InstallError, match="MANIFESTHUB_API_URL"):
        prepare_manifests(settings, manifests_dir=_manifests_dir(tmp_path), source=cast("DownloadIO", download))
    download.check_manifest_support.assert_not_called()
