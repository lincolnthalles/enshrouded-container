"""Tests for Auto Pause save-signature discovery."""

from os import utime
from typing import TYPE_CHECKING

from enshctl.lifecycle.saves import SaveSignature, newest_save_signature

if TYPE_CHECKING:
    from pathlib import Path


def _write_save(path: Path, content: bytes, *, mtime_ns: int) -> None:
    path.write_bytes(content)
    utime(path, ns=(mtime_ns, mtime_ns))


def test_newest_save_signature_uses_modification_time(tmp_path: Path) -> None:
    # GIVEN two top-level save files
    _write_save(tmp_path / "world1.ksd", b"one", mtime_ns=1_000)
    _write_save(tmp_path / "world2.ksd", b"two!", mtime_ns=2_000)

    # WHEN the newest signature is read
    signature = newest_save_signature(tmp_path)

    # THEN the newest file and its size/mtime are returned
    assert signature == SaveSignature(tmp_path / "world2.ksd", 4, 2_000)


def test_newest_save_signature_ignores_nested_and_other_files(tmp_path: Path) -> None:
    # GIVEN nested saves and non-ksd files
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_save(nested / "nested.ksd", b"nested", mtime_ns=9_000)
    _write_save(tmp_path / "backup.zip", b"zip", mtime_ns=10_000)

    # WHEN the newest top-level signature is read
    signature = newest_save_signature(tmp_path)

    # THEN no save is reported
    assert signature is None


def test_newest_save_signature_returns_none_for_missing_directory(tmp_path: Path) -> None:
    assert newest_save_signature(tmp_path / "missing") is None
