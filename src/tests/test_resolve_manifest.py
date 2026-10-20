"""Tests for latest manifest control file and resolve_manifest fallback."""

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


def test_resolve_manifest_explicit_id_skips_control(tmp_path: Path) -> None:
    control = tmp_path / ".latest-manifest"
    result = manifests.resolve_manifest("12345", control_file=control)
    assert result == "12345"
    assert not control.exists()
