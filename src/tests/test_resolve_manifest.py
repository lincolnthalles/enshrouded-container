"""Tests for latest manifest control file and resolve_manifest fallback."""

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from enshctl import install

if TYPE_CHECKING:
    from pathlib import Path


def test_write_latest_manifest_creates_file(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        install._write_latest_manifest("1234567890", "05/29/2026 12:00:00")
    assert control.read_text().strip() == "1234567890-05/29/2026 12:00:00"


def test_write_latest_manifest_skips_when_unchanged(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("1234567890-05/29/2026 12:00:00")
    original_mtime = control.stat().st_mtime_ns
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        install._write_latest_manifest("1234567890", "05/29/2026 12:00:00")
    assert control.stat().st_mtime_ns == original_mtime


def test_write_latest_manifest_updates_on_change(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("old-id-01/01/2020 00:00:00")
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        install._write_latest_manifest("999999", "06/01/2026 08:30:00")
    assert control.read_text().strip() == "999999-06/01/2026 08:30:00"


def test_read_latest_manifest_missing_file(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        result = install._read_latest_manifest()
    assert result is None


def test_read_latest_manifest_empty_file(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("")
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        result = install._read_latest_manifest()
    assert result is None


def test_read_latest_manifest_valid(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("2174935030716737236-05/29/2026 12:00:00")
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        result = install._read_latest_manifest()
    assert result == "2174935030716737236"


def test_read_latest_manifest_malformed(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("not-a-number-something")
    with patch.object(install, "LATEST_MANIFEST_FILE", control):
        result = install._read_latest_manifest()
    assert result is None


def test_resolve_manifest_latest_writes_control(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    manifests = [{"manifest_id": "111", "timestamp": "05/29/2026 12:00:00", "branch": "public"}]
    with (
        patch.object(install, "LATEST_MANIFEST_FILE", control),
        patch.object(install, "fetch_manifests", return_value=manifests),
    ):
        result = install.resolve_manifest("latest")
    assert result == "111"
    assert control.read_text().strip() == "111-05/29/2026 12:00:00"


def test_resolve_manifest_latest_fallback_to_cached(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    control.write_text("999999-05/29/2026 12:00:00")
    with (
        patch.object(install, "LATEST_MANIFEST_FILE", control),
        patch.object(install, "fetch_manifests", return_value=[]),
    ):
        result = install.resolve_manifest("latest")
    assert result == "999999"


def test_resolve_manifest_latest_no_cache_no_manifests_exits(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    with (
        patch.object(install, "LATEST_MANIFEST_FILE", control),
        patch.object(install, "fetch_manifests", return_value=[]),
        pytest.raises(SystemExit),
    ):
        install.resolve_manifest("latest")


def test_resolve_manifest_explicit_id_skips_control(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    with (
        patch.object(install, "LATEST_MANIFEST_FILE", control),
        patch.object(install, "fetch_manifests", return_value=[]),
    ):
        result = install.resolve_manifest("12345")
    assert result == "12345"
    assert not control.exists()
