"""Tests for Version spec resolution and the latest-manifest control file."""

import logging
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from enshctl import manifests
from enshctl.download.types import InstallError, ManifestRecord

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_manifest_latest_writes_control(tmp_path: Path) -> None:
    # GIVEN one listed Manifest and no recorded control file
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00")]

    # WHEN resolving latest
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)

    # THEN the resolved ID is recorded with its timestamp
    assert result == "111"
    assert control.read_text().strip() == "111-05/29/2026 12:00:00"


def test_resolve_manifest_latest_fallback_to_cached(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a recorded manifest and an empty listing
    control = tmp_path / ".latest-manifest"
    control.write_text("999999-05/29/2026 12:00:00")

    # WHEN resolving latest
    with caplog.at_level(logging.WARNING, logger="enshctl.manifests"):
        result = manifests.resolve_manifest("latest", control_file=control, fetch=list)

    # THEN the recorded manifest is used with a warning naming it
    assert result == "999999"
    assert "cached manifest 999999" in caplog.text


def test_resolve_manifest_latest_no_cache_no_manifests_raises(tmp_path: Path) -> None:
    # GIVEN no recorded manifest and an empty listing
    control = tmp_path / ".latest-manifest"

    # WHEN resolving latest
    # THEN resolution fails instead of guessing a Manifest
    with pytest.raises(InstallError, match="no cached manifest"):
        manifests.resolve_manifest("latest", control_file=control, fetch=list)


def test_resolve_manifest_latest_rewrites_control_on_change(tmp_path: Path) -> None:
    # GIVEN a stale recorded manifest
    control = tmp_path / ".latest-manifest"
    control.write_text("old-id-01/01/2020 00:00:00")
    found = [ManifestRecord(manifest_id="999999", timestamp="06/01/2026 08:30:00")]

    # WHEN resolving latest
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)

    # THEN the recorded manifest is replaced with the resolved ID and timestamp
    assert result == "999999"
    assert control.read_text().strip() == "999999-06/01/2026 08:30:00"


def test_resolve_manifest_latest_keeps_mtime_when_unchanged(tmp_path: Path) -> None:
    # GIVEN a recorded manifest matching the next resolution, with an old mtime
    control = tmp_path / ".latest-manifest"
    control.write_text("111-05/29/2026 12:00:00")
    os.utime(control, (1_000_000, 1_000_000))
    recorded = control.stat().st_mtime_ns
    found = [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00")]

    # WHEN resolving latest again
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)

    # THEN the file is not rewritten
    assert result == "111"
    assert control.stat().st_mtime_ns == recorded


def test_resolve_manifest_empty_control_without_listing_raises(tmp_path: Path) -> None:
    # GIVEN an empty control file and no listed manifests
    control = tmp_path / ".latest-manifest"
    control.write_text("")

    # WHEN resolving latest
    # THEN the empty record is not treated as a cached manifest
    with pytest.raises(InstallError, match="no cached manifest"):
        manifests.resolve_manifest("latest", control_file=control, fetch=list)


def test_resolve_manifest_malformed_control_warns_and_raises(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a malformed control file and no listed manifests
    control = tmp_path / ".latest-manifest"
    control.write_text("not-a-number-something")

    # WHEN resolving latest
    with (
        caplog.at_level(logging.WARNING, logger="enshctl.manifests"),
        pytest.raises(InstallError, match="no cached manifest"),
    ):
        manifests.resolve_manifest("latest", control_file=control, fetch=list)

    # THEN the malformed record is reported and the fallback is skipped
    assert "Malformed control file" in caplog.text


def test_resolve_manifest_latest_uses_default_listing(tmp_path: Path) -> None:
    # GIVEN no injected fetcher
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="777", timestamp="05/29/2026 12:00:00")]

    with patch("enshctl.manifests.DepotDownloader") as mock_adapter:
        mock_adapter.return_value.fetch_manifests.return_value = found
        # WHEN resolving latest
        result = manifests.resolve_manifest("latest", control_file=control)

    # THEN the DepotDownloader adapter supplies the listing and the control file is updated
    assert result == "777"
    assert control.read_text().strip() == "777-05/29/2026 12:00:00"
    mock_adapter.return_value.fetch_manifests.assert_called_once_with()


def test_resolve_manifest_latest_picks_newest_across_months(tmp_path: Path) -> None:
    # GIVEN Manifests listed out of chronological order across a year boundary
    control = tmp_path / ".latest-manifest"
    found = [
        ManifestRecord(manifest_id="older", timestamp="12/15/2025 12:00:00"),
        ManifestRecord(manifest_id="newer", timestamp="01/05/2026 12:00:00"),
    ]

    # WHEN resolving latest
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)

    # THEN the chronologically newest Manifest wins
    assert result == "newer"


def test_resolve_manifest_latest_orders_tab_separated_timestamp(tmp_path: Path) -> None:
    # GIVEN a newer Manifest whose timestamp uses a tab separator
    control = tmp_path / ".latest-manifest"
    found = [
        ManifestRecord(manifest_id="older", timestamp="01/01/2020 00:00:00"),
        ManifestRecord(manifest_id="newer", timestamp="05/29/2026\t12:00:00"),
    ]

    # WHEN resolving latest
    result = manifests.resolve_manifest("latest", control_file=control, fetch=lambda: found)

    # THEN the newer Manifest wins instead of sorting as a zero timestamp
    assert result == "newer"


def test_resolve_manifest_explicit_id_skips_control(tmp_path: Path) -> None:
    # GIVEN an explicit numeric Version spec
    control = tmp_path / ".latest-manifest"

    # WHEN resolving it
    result = manifests.resolve_manifest("12345", control_file=control)

    # THEN the ID is used without consulting or writing the control file
    assert result == "12345"
    assert not control.exists()


def test_resolve_manifest_build_unknown_id_warns_with_id(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a build ID matching no listed manifest
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00")]
    # WHEN resolving the unknown build ID
    with caplog.at_level(logging.WARNING, logger="enshctl.manifests"):
        result = manifests.resolve_manifest("build:999", control_file=control, fetch=lambda: found)
    # THEN it falls back to the raw ID with a warning naming it instead of crashing
    assert result == "999"
    assert "999" in caplog.text


def test_resolve_manifest_build_matches_manifest_suffix(tmp_path: Path) -> None:
    # GIVEN a Manifest whose ID ends with the build value
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="123999", timestamp="05/29/2026 12:00:00")]

    # WHEN resolving the build
    result = manifests.resolve_manifest("build:999", control_file=control, fetch=lambda: found)

    # THEN the matching Manifest ID is used
    assert result == "123999"


def test_resolve_manifest_build_matches_branch(tmp_path: Path) -> None:
    # GIVEN a Manifest whose branch matches the build value
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00", branch="release-999")]

    # WHEN resolving the build
    result = manifests.resolve_manifest("build:release-999", control_file=control, fetch=lambda: found)

    # THEN the matching Manifest ID is used
    assert result == "111"


def test_resolve_manifest_build_non_numeric_rejected(tmp_path: Path) -> None:
    # GIVEN a non-numeric build ID matching no listed manifest
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00")]

    # WHEN resolving the unknown build ID
    # THEN it fails instead of using the value as a Manifest ID
    with pytest.raises(InstallError, match="numeric Manifest ID"):
        manifests.resolve_manifest("build:not-a-number", control_file=control, fetch=lambda: found)


def test_resolve_manifest_empty_build_rejected(tmp_path: Path) -> None:
    # GIVEN an empty build ID
    control = tmp_path / ".latest-manifest"
    found = [ManifestRecord(manifest_id="111", timestamp="05/29/2026 12:00:00")]

    # WHEN resolving the empty build ID
    # THEN it fails instead of matching the first manifest
    with pytest.raises(InstallError, match="Build ID is empty"):
        manifests.resolve_manifest("build:", control_file=control, fetch=lambda: found)


def test_resolve_manifest_latest_fetch_failure_uses_cache(tmp_path: Path) -> None:
    import subprocess

    # GIVEN a cached manifest and a DepotDownloader listing that fails
    control = tmp_path / ".latest-manifest"
    control.write_text("999999-05/29/2026 12:00:00")

    def _fail() -> list[ManifestRecord]:
        raise subprocess.CalledProcessError(1, ["DepotDownloader", "-manifest-only"])

    # WHEN resolving latest
    result = manifests.resolve_manifest("latest", control_file=control, fetch=_fail)
    # THEN the cached manifest is used instead of propagating the failure
    assert result == "999999"


def test_resolve_manifest_latest_fetch_failure_no_cache_raises(tmp_path: Path) -> None:
    import subprocess

    # GIVEN no cached manifest and a DepotDownloader listing that fails
    control = tmp_path / ".latest-manifest"

    def _fail() -> list[ManifestRecord]:
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

    def _fail() -> list[ManifestRecord]:
        raise subprocess.CalledProcessError(1, ["DepotDownloader", "-manifest-only"])

    # WHEN resolving a build ID
    with pytest.raises(InstallError, match="Manifest listing failed") as exc_info:
        manifests.resolve_manifest("build:999", control_file=control, fetch=_fail)
    # THEN the listing failure is chained as the cause instead of silently treating the build as a manifest ID
    assert isinstance(exc_info.value.__cause__, subprocess.CalledProcessError)


def test_latest_manifest_returns_newest_without_writing_cache() -> None:
    # GIVEN two listed Manifests out of order
    found = [
        ManifestRecord("older", "12/15/2025 12:00:00"),
        ManifestRecord("newer", "01/05/2026 12:00:00"),
    ]

    # WHEN selecting the latest candidate
    with patch.object(manifests, "record_latest_manifest") as mock_record:
        result = manifests.latest_manifest(fetch=lambda: found)

    # THEN the newest Manifest is returned and the cache write is not invoked
    assert result == ManifestRecord("newer", "01/05/2026 12:00:00")
    mock_record.assert_not_called()


def test_latest_manifest_empty_listing_returns_none() -> None:
    # GIVEN an empty listing
    # WHEN selecting the latest candidate
    # THEN no candidate exists
    assert manifests.latest_manifest(fetch=list) is None


def test_cached_latest_manifest_round_trips(tmp_path: Path) -> None:
    # GIVEN a recorded Manifest ID and timestamp
    control = tmp_path / ".latest-manifest"
    control.write_text("999-05/29/2026 12:00:00")

    # WHEN reading the cache
    result = manifests.cached_latest_manifest(control)

    # THEN both values are returned
    assert result == ManifestRecord("999", "05/29/2026 12:00:00")


def test_cached_latest_manifest_rejects_malformed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a malformed control file
    control = tmp_path / ".latest-manifest"
    control.write_text("not-a-manifest")

    # WHEN reading the cache
    with caplog.at_level(logging.WARNING, logger="enshctl.manifests"):
        result = manifests.cached_latest_manifest(control)

    # THEN the cache is ignored with a warning
    assert result is None
    assert "Malformed control file" in caplog.text
