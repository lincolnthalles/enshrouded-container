"""Tests for latest manifest control file and resolve_manifest fallback."""

import logging
from typing import TYPE_CHECKING

import pytest
from enshctl import manifests
from enshctl.download import InstallError

if TYPE_CHECKING:
    from pathlib import Path


def test_write_latest_manifest_creates_file(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    manifests._write_latest_manifest("1234567890", "05/29/2026 12:00:00", control)
    assert control.read_text().strip() == "1234567890-05/29/2026 12:00:00"


def test_write_latest_manifest_skips_when_unchanged(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("1234567890-05/29/2026 12:00:00")
    original_mtime = control.stat().st_mtime_ns
    manifests._write_latest_manifest("1234567890", "05/29/2026 12:00:00", control)
    assert control.stat().st_mtime_ns == original_mtime


def test_write_latest_manifest_updates_on_change(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("old-id-01/01/2020 00:00:00")
    manifests._write_latest_manifest("999999", "06/01/2026 08:30:00", control)
    assert control.read_text().strip() == "999999-06/01/2026 08:30:00"


def test_read_latest_manifest_missing_file(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    result = manifests._read_latest_manifest(control)
    assert result is None


def test_read_latest_manifest_empty_file(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("")
    result = manifests._read_latest_manifest(control)
    assert result is None


def test_read_latest_manifest_valid(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("2174935030716737236-05/29/2026 12:00:00")
    result = manifests._read_latest_manifest(control)
    assert result == "2174935030716737236"


def test_read_latest_manifest_malformed(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("not-a-number-something")
    result = manifests._read_latest_manifest(control)
    assert result is None


def test_resolve_manifest_latest_writes_control(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    found = [{"manifest_id": "111", "timestamp": "05/29/2026 12:00:00", "branch": "public"}]
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)
    assert result == "111"
    assert control.read_text().strip() == "111-05/29/2026 12:00:00"


def test_resolve_manifest_latest_fallback_to_cached(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("999999-05/29/2026 12:00:00")
    result = manifests.resolve_manifest("latest", control_file=control, fetch=list)
    assert result == "999999"


def test_resolve_manifest_latest_no_cache_no_manifests_raises(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    with pytest.raises(InstallError):
        manifests.resolve_manifest("latest", control_file=control, fetch=list)


def test_resolve_manifest_latest_picks_newest_across_months(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    found = [
        {"manifest_id": "older", "timestamp": "12/15/2025 12:00:00", "branch": "public"},
        {"manifest_id": "newer", "timestamp": "01/05/2026 12:00:00", "branch": "public"},
    ]
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)
    assert result == "newer"


def test_resolve_manifest_explicit_id_skips_control(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    result = manifests.resolve_manifest("12345", control_file=control)
    assert result == "12345"
    assert not control.exists()


def test_resolve_manifest_build_unknown_id_warns_with_id(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a build ID matching no listed manifest
    control = tmp_path / ".latest-manifest"
    found = [{"manifest_id": "111", "timestamp": "05/29/2026 12:00:00", "branch": "public"}]
    # WHEN resolving the unknown build ID
    with caplog.at_level(logging.WARNING, logger="enshctl.manifests"):
        result = manifests.resolve_manifest("build:999", control_file=control, fetch=lambda: found)
    # THEN it falls back to the raw ID with a warning naming it instead of crashing
    assert result == "999"
    assert "999" in caplog.text


def test_resolve_manifest_build_non_numeric_rejected(tmp_path: Path) -> None:
    # GIVEN a non-numeric build ID matching no listed manifest
    control = tmp_path / ".latest-manifest"
    found = [{"manifest_id": "111", "timestamp": "05/29/2026 12:00:00", "branch": "public"}]

    # WHEN resolving the unknown build ID
    # THEN it fails instead of using the value as a Manifest ID
    with pytest.raises(InstallError, match="numeric Manifest ID"):
        manifests.resolve_manifest("build:not-a-number", control_file=control, fetch=lambda: found)


def test_resolve_manifest_empty_build_rejected(tmp_path: Path) -> None:
    # GIVEN an empty build ID
    control = tmp_path / ".latest-manifest"
    found = [{"manifest_id": "111", "timestamp": "05/29/2026 12:00:00", "branch": "public"}]

    # WHEN resolving the empty build ID
    # THEN it fails instead of matching the first manifest
    with pytest.raises(InstallError, match="Build ID is empty"):
        manifests.resolve_manifest("build:", control_file=control, fetch=lambda: found)


def test_resolve_manifest_latest_fetch_failure_uses_cache(tmp_path: Path) -> None:
    import subprocess

    # GIVEN a cached manifest and a DepotDownloader listing that fails
    control = tmp_path / ".latest-manifest"
    control.write_text("999999-05/29/2026 12:00:00")

    def _fail() -> list[dict[str, str]]:
        raise subprocess.CalledProcessError(1, ["DepotDownloader", "-manifest-only"])

    # WHEN resolving latest
    result = manifests.resolve_manifest("latest", control_file=control, fetch=_fail)
    # THEN the cached manifest is used instead of propagating the failure
    assert result == "999999"


def test_resolve_manifest_latest_fetch_failure_no_cache_raises(tmp_path: Path) -> None:
    import subprocess

    # GIVEN no cached manifest and a DepotDownloader listing that fails
    control = tmp_path / ".latest-manifest"

    def _fail() -> list[dict[str, str]]:
        raise subprocess.CalledProcessError(1, ["DepotDownloader", "-manifest-only"])

    # WHEN resolving latest
    with pytest.raises(InstallError, match="Manifest listing failed") as exc_info:
        manifests.resolve_manifest("latest", control_file=control, fetch=_fail)
    # THEN the listing failure is chained as the cause instead of being dropped
    assert isinstance(exc_info.value.__cause__, subprocess.CalledProcessError)


def test_resolve_manifest_build_fetch_failure_raises(tmp_path: Path) -> None:
    import subprocess

    # GIVEN a DepotDownloader listing that fails
    control = tmp_path / ".latest-manifest"

    def _fail() -> list[dict[str, str]]:
        raise subprocess.CalledProcessError(1, ["DepotDownloader", "-manifest-only"])

    # WHEN resolving a build ID
    with pytest.raises(InstallError, match="Manifest listing failed") as exc_info:
        manifests.resolve_manifest("build:999", control_file=control, fetch=_fail)
    # THEN the listing failure is chained as the cause instead of silently treating the build as a manifest ID
    assert isinstance(exc_info.value.__cause__, subprocess.CalledProcessError)


def test_manifestfile_support_probe_lists_no_args() -> None:
    from unittest.mock import MagicMock, patch

    # GIVEN the DepotDownloader probe
    manifests.check_manifestfile_support.cache_clear()
    try:
        # WHEN probing support
        with patch.object(
            manifests.subprocess,
            "run",
            return_value=MagicMock(stdout=" -manifestfile <file>\n -depotkeys <file>\n", stderr=""),
        ) as mock_run:
            assert manifests.check_manifestfile_support() is True
        # THEN the probe passes no arguments, avoiding any network or download
        assert mock_run.call_args.args[0] == [*manifests.DEPOT_DOWNLOADER]
    finally:
        manifests.check_manifestfile_support.cache_clear()


def test_manifestfile_support_detects_vanilla() -> None:
    from unittest.mock import MagicMock, patch

    # GIVEN a DepotDownloader whose usage lacks the Mod-fork flags
    manifests.check_manifestfile_support.cache_clear()
    try:
        # WHEN probing support
        with patch.object(
            manifests.subprocess,
            "run",
            return_value=MagicMock(stdout="Usage: depotdownloader -app <id>\n", stderr=""),
        ):
            # THEN vanilla is detected as unsupported
            assert manifests.check_manifestfile_support() is False
    finally:
        manifests.check_manifestfile_support.cache_clear()


def test_manifestfile_support_timeout_presumes_support() -> None:
    import subprocess
    from unittest.mock import patch

    # GIVEN a probe that times out (fork proceeding to network)
    manifests.check_manifestfile_support.cache_clear()
    try:
        # WHEN probing support
        with patch.object(
            manifests.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("dd", 30),
        ):
            # THEN support is presumed rather than blocking Install
            assert manifests.check_manifestfile_support() is True
    finally:
        manifests.check_manifestfile_support.cache_clear()
