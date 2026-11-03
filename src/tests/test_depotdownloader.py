"""Tests for the DepotDownloader adapter argv and output parsing."""

import logging
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from enshctl.download.depotdownloader import DepotDownloader, with_manifest_override
from enshctl.download.types import DownloadConfig, InstallError, ManifestRecord
from enshctl.paths import APP_ID, DEPOT_DOWNLOADER, DEPOT_ID, MANIFEST_TMP_DIR

if TYPE_CHECKING:
    from pathlib import Path

_LOGGER = "enshctl.download.depotdownloader"


def _result(stdout: str = "", *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["DepotDownloader"], returncode=returncode, stdout=stdout, stderr="")


def _download(downloader: DepotDownloader, target: Path, config: DownloadConfig | None = None) -> None:
    downloader.download_depots("999", target, config if config is not None else DownloadConfig(), [(DEPOT_ID, "999")])


def test_fetch_manifests_lists_target_depot_with_windows_os() -> None:
    # GIVEN a listing that reports one Manifest for the target depot
    run = MagicMock(return_value=_result("Manifest 111 (05/29/2026 12:00:00)\n"))

    # WHEN fetching Manifests for Version resolution
    records = DepotDownloader(run=run).fetch_manifests()

    # THEN the exact argv targets the depot and the Windows platform
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-dir",
            MANIFEST_TMP_DIR,
            "-manifest-only",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert records == [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00")]


def test_fetch_manifests_ignores_manifest_split_across_lines() -> None:
    # GIVEN a listing whose Manifest label is split across lines
    run = MagicMock(return_value=_result("Manifest\n111 (05/29/2026 12:00:00)\n"))

    # WHEN fetching Manifests
    records = DepotDownloader(run=run).fetch_manifests()

    # THEN the malformed listing is not parsed
    assert records == []


def test_list_manifest_ids_lists_target_depot_with_windows_os() -> None:
    # GIVEN a listing that reports two Manifests for the target depot
    run = MagicMock(
        return_value=_result(
            "Manifest 111 (05/29/2026 12:00:00)\nManifest 222 (06/01/2026 08:30:00)\n",
        ),
    )

    # WHEN listing Manifest IDs for prefetching
    manifest_ids = DepotDownloader(run=run).list_manifest_ids()

    # THEN the exact argv targets the depot and selects the Windows platform
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-dir",
            MANIFEST_TMP_DIR,
            "-manifest-only",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert manifest_ids == ["111", "222"]


def test_list_manifest_ids_warns_when_empty(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a listing without Manifest lines
    run = MagicMock(return_value=_result("No manifests\n"))

    # WHEN listing Manifest IDs
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        manifest_ids = DepotDownloader(run=run).list_manifest_ids()

    # THEN the empty result is reported with a warning
    assert manifest_ids == []
    assert any("No manifests discovered" in record.message for record in caplog.records)


def test_discover_depots_queries_each_depot_with_windows_os() -> None:
    # GIVEN an app-level depot listing and per-depot manifest listings
    run = MagicMock(
        side_effect=[
            _result("Got depot key for 1004 result: OK\nGot depot key for 2278521 result: OK\n"),
            _result("Manifest 7604377918839582995 (09/15/2026 18:29:04)\n"),
            _result("Manifest 981291927487372437 (10/30/2026 09:32:12)\n"),
        ],
    )

    # WHEN discovering depots
    discovered = DepotDownloader(run=run).discover_depots()

    # THEN the app-level query and both per-depot queries pin the platform
    assert run.call_args_list == [
        call(
            [
                *DEPOT_DOWNLOADER,
                "-app",
                APP_ID,
                "-os",
                "windows",
                "-dir",
                MANIFEST_TMP_DIR,
                "-manifest-only",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        ),
        call(
            [
                *DEPOT_DOWNLOADER,
                "-app",
                APP_ID,
                "-depot",
                "1004",
                "-os",
                "windows",
                "-dir",
                MANIFEST_TMP_DIR,
                "-manifest-only",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        ),
        call(
            [
                *DEPOT_DOWNLOADER,
                "-app",
                APP_ID,
                "-depot",
                "2278521",
                "-os",
                "windows",
                "-dir",
                MANIFEST_TMP_DIR,
                "-manifest-only",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        ),
    ]
    assert discovered == [("1004", "7604377918839582995"), ("2278521", "981291927487372437")]


def test_discover_depots_reports_missing_manifest_as_empty() -> None:
    # GIVEN a depot listing followed by a per-depot listing without a Manifest
    run = MagicMock(
        side_effect=[
            _result("Got depot key for 1004 result: OK\n"),
            _result("Nothing here\n"),
        ],
    )

    # WHEN discovering depots
    discovered = DepotDownloader(run=run).discover_depots()

    # THEN the depot is retained with an empty Manifest ID
    assert discovered == [("1004", "")]


def test_discover_depots_returns_empty_without_depot_keys() -> None:
    # GIVEN an app-level listing without depot keys
    run = MagicMock(return_value=_result("No depots\n"))

    # WHEN discovering depots
    discovered = DepotDownloader(run=run).discover_depots()

    # THEN no per-depot query runs
    assert discovered == []
    assert run.call_count == 1


def test_download_depots_builds_anonymous_command(tmp_path: Path) -> None:
    # GIVEN the anonymous strategy
    run = MagicMock(return_value=_result())

    # WHEN downloading the target depot
    _download(DepotDownloader(run=run), tmp_path)

    # THEN the exact argv carries no credential inputs
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-max-downloads",
            "8",
            "-validate",
            "-verify-all",
            "-dir",
            str(tmp_path),
            "-manifest",
            "999",
        ],
        check=False,
        timeout=3600,
    )


def test_download_depots_builds_auth_free_command(tmp_path: Path) -> None:
    # GIVEN the auth-free strategy with keys and a Manifest file
    run = MagicMock(return_value=_result())
    config = DownloadConfig(
        use_manifestfile=True,
        manifest_file=tmp_path / "999.manifest",
        depot_keys_path=tmp_path / "depot.keys",
    )

    # WHEN downloading the target depot
    _download(DepotDownloader(run=run), tmp_path, config)

    # THEN the exact argv passes the keys and Manifest file with no login flags
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-max-downloads",
            "8",
            "-validate",
            "-verify-all",
            "-dir",
            str(tmp_path),
            "-manifest",
            "999",
            "-depotkeys",
            str(tmp_path / "depot.keys"),
            "-manifestfile",
            str(tmp_path / "999.manifest"),
        ],
        check=False,
        timeout=3600,
    )


def test_download_depots_builds_steam_command(tmp_path: Path) -> None:
    # GIVEN the Steam strategy with a username and password
    run = MagicMock(return_value=_result())
    config = DownloadConfig(username="user", password="secret")

    # WHEN downloading the target depot
    _download(DepotDownloader(run=run), tmp_path, config)

    # THEN the exact argv persists the login and passes the password
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-max-downloads",
            "8",
            "-validate",
            "-verify-all",
            "-dir",
            str(tmp_path),
            "-manifest",
            "999",
            "-username",
            "user",
            "-password",
            "secret",
            "-remember-password",
        ],
        check=False,
        timeout=3600,
    )


def test_download_depots_builds_steam_command_without_password(tmp_path: Path) -> None:
    # GIVEN the Steam strategy with a username only
    run = MagicMock(return_value=_result())
    config = DownloadConfig(username="user")

    # WHEN downloading the target depot
    _download(DepotDownloader(run=run), tmp_path, config)

    # THEN the exact argv omits the password but still persists the login
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-max-downloads",
            "8",
            "-validate",
            "-verify-all",
            "-dir",
            str(tmp_path),
            "-manifest",
            "999",
            "-username",
            "user",
            "-remember-password",
        ],
        check=False,
        timeout=3600,
    )


def test_download_depots_omits_manifest_for_empty_discovered_id(tmp_path: Path) -> None:
    # GIVEN a discovered depot without a Manifest ID
    run = MagicMock(return_value=_result())

    # WHEN downloading that depot
    DepotDownloader(run=run).download_depots("999", tmp_path, DownloadConfig(), [(DEPOT_ID, "")])

    # THEN the exact argv omits -manifest
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-max-downloads",
            "8",
            "-validate",
            "-verify-all",
            "-dir",
            str(tmp_path),
        ],
        check=False,
        timeout=3600,
    )


def test_download_depots_discovers_and_pins_when_unset(tmp_path: Path) -> None:
    # GIVEN discovery output and two depot downloads
    run = MagicMock(
        side_effect=[
            _result("Got depot key for 1004 result: OK\nGot depot key for 2278521 result: OK\n"),
            _result("Manifest 7604377918839582995 (09/15/2026 18:29:04)\n"),
            _result("Manifest 981291927487372437 (10/30/2026 09:32:12)\n"),
            _result(),
            _result(),
        ],
    )

    # WHEN downloading without an explicit depot list
    DepotDownloader(run=run).download_depots("999", tmp_path, DownloadConfig())

    # THEN the target depot is pinned while the other keeps its discovered Manifest
    assert run.call_count == 5
    first_download = run.call_args_list[3].args[0]
    second_download = run.call_args_list[4].args[0]
    assert first_download[first_download.index("-depot") + 1] == "1004"
    assert first_download[first_download.index("-manifest") + 1] == "7604377918839582995"
    assert second_download[second_download.index("-depot") + 1] == DEPOT_ID
    assert second_download[second_download.index("-manifest") + 1] == "999"


def test_download_depots_builds_qr_command(tmp_path: Path) -> None:
    # GIVEN the interactive QR strategy
    run = MagicMock(return_value=_result())
    config = DownloadConfig(use_qr=True, print_qr_message=True)

    # WHEN downloading the target depot
    _download(DepotDownloader(run=run), tmp_path, config)

    # THEN the exact argv requests QR login
    run.assert_called_once_with(
        [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            DEPOT_ID,
            "-os",
            "windows",
            "-max-downloads",
            "8",
            "-validate",
            "-verify-all",
            "-dir",
            str(tmp_path),
            "-manifest",
            "999",
            "-qr",
        ],
        check=False,
        timeout=3600,
    )


def test_download_depots_fails_on_nonzero_exit(tmp_path: Path) -> None:
    # GIVEN a DepotDownloader that exits non-zero
    run = MagicMock(return_value=_result(returncode=1))

    # WHEN downloading the target depot
    # THEN the Install fails with an error naming the depot and exit code
    with pytest.raises(InstallError, match=f"code 1 for depot {DEPOT_ID}"):
        _download(DepotDownloader(run=run), tmp_path)


def test_download_depots_fails_on_timeout(tmp_path: Path) -> None:
    # GIVEN a DepotDownloader that exceeds the download window
    run = MagicMock(side_effect=subprocess.TimeoutExpired("DepotDownloader", 3600))

    # WHEN downloading the target depot
    # THEN the Install fails with an error naming the timeout
    with pytest.raises(InstallError, match="timed out"):
        _download(DepotDownloader(run=run), tmp_path)


def test_with_manifest_override_pins_only_target_depot() -> None:
    # GIVEN discovered depots with their own Manifest IDs
    discovered = [("1004", "111"), (DEPOT_ID, "222")]

    # WHEN overriding the target depot
    pinned = with_manifest_override(discovered, "999")

    # THEN only the target depot changes
    assert pinned == [("1004", "111"), (DEPOT_ID, "999")]


def test_supports_manifestfile_probes_with_no_arguments() -> None:
    # GIVEN a binary whose usage documents the Manifest-file flags
    run = MagicMock(return_value=_result(" -manifestfile <file>\n -depotkeys <file>\n"))

    # WHEN probing support
    supported = DepotDownloader(run=run).supports_manifestfile()

    # THEN the exact argv is the bare binary, avoiding network and downloads
    run.assert_called_once_with(
        [*DEPOT_DOWNLOADER],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert supported is True


def test_supports_manifestfile_detects_vanilla() -> None:
    # GIVEN a binary whose usage lacks the Manifest-file flags
    run = MagicMock(return_value=_result("Usage: depotdownloader -app <id>\n"))

    # WHEN probing support
    supported = DepotDownloader(run=run).supports_manifestfile()

    # THEN vanilla is detected as unsupported
    assert supported is False


def test_supports_manifestfile_presumes_support_on_timeout() -> None:
    # GIVEN a probe that times out
    run = MagicMock(side_effect=subprocess.TimeoutExpired("DepotDownloader", 30))

    # WHEN probing support
    supported = DepotDownloader(run=run).supports_manifestfile()

    # THEN support is presumed instead of blocking the Install
    assert supported is True


def test_supports_manifestfile_caches_each_seam() -> None:
    # GIVEN two probes with opposite results
    supported_run = MagicMock(return_value=_result(" -manifestfile <file>\n -depotkeys <file>\n"))
    vanilla_run = MagicMock(return_value=_result("Usage: depotdownloader -app <id>\n"))
    supported = DepotDownloader(run=supported_run)
    vanilla = DepotDownloader(run=vanilla_run)

    # WHEN probing each twice
    assert supported.supports_manifestfile() is True
    assert vanilla.supports_manifestfile() is False
    assert supported.supports_manifestfile() is True
    assert vanilla.supports_manifestfile() is False

    # THEN each seam probes once and the results do not leak
    assert supported_run.call_count == 1
    assert vanilla_run.call_count == 1
