"""Tests for restore atomic swap (extract-to-tmp then move)."""

from typing import TYPE_CHECKING

import pytest
from enshctl.restore import RestoreError, restore_backup

if TYPE_CHECKING:
    from pathlib import Path


def _extract_new(_src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "new_save.db").write_bytes(b"new")


class TestRestoreAtomicSwap:
    """Tests for the restore atomic swap pattern."""

    def test_successful_restore_uses_tmp_then_swaps(self, tmp_path: Path) -> None:
        # GIVEN existing saves and a backup
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"

        # WHEN restoring with ample free space
        restore_backup(
            backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, extract=_extract_new, disk_free=lambda _p: 10 * 1024**3
        )

        # THEN new saves replace old and tmp is cleaned up
        assert not tmp_dir.exists(), "tmp directory should be removed"
        assert (saves_dir / "new_save.db").read_bytes() == b"new"
        assert not (saves_dir / "old_save.db").exists(), "old saves should be gone"

    def test_extraction_failure_leaves_saves_untouched(self, tmp_path: Path) -> None:
        # GIVEN existing saves and a backup whose extraction fails
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"

        def _fail(_src: Path, _dst: Path) -> None:
            msg = "ENOSPC"
            raise OSError(msg)

        # WHEN restoring
        with pytest.raises(RestoreError):
            restore_backup(backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, extract=_fail, disk_free=lambda _p: 0)

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on failure"

    def test_space_check_failure_cleans_tmp_and_aborts(self, tmp_path: Path) -> None:
        # GIVEN existing saves and extracted data larger than free space
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"

        def _extract_bigger(_src: Path, dst: Path) -> None:
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "bigger_file.db").write_bytes(b"bigger")

        # WHEN restoring with no free space
        with pytest.raises(RestoreError):
            restore_backup(
                backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, extract=_extract_bigger, disk_free=lambda _p: 0
            )

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on space check failure"

    def test_pre_existing_tmp_removed_before_extract(self, tmp_path: Path) -> None:
        # GIVEN a stale tmp directory and existing saves
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"
        tmp_dir.mkdir()
        (tmp_dir / "stale_file.tmp").write_bytes(b"stale")

        def _extract_fresh(_src: Path, dst: Path) -> None:
            assert not (tmp_dir / "stale_file.tmp").exists(), "stale file should be removed first"
            (dst / "new_save.db").write_bytes(b"new")

        # WHEN restoring with ample free space
        restore_backup(
            backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, extract=_extract_fresh, disk_free=lambda _p: 10 * 1024**3
        )

        # THEN the restore completes
        assert (saves_dir / "new_save.db").read_bytes() == b"new"

    def test_corrupt_zstd_cleans_tmp_and_aborts(self, tmp_path: Path) -> None:
        import zstandard

        # GIVEN a truncated zstd archive and existing saves
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        cctx = zstandard.ZstdCompressor()
        backup_path.write_bytes(cctx.compress(b"not a tar stream")[:10])
        tmp_dir = tmp_path / "saves-restore-tmp"

        # WHEN restoring the corrupt archive with the real extractor
        with pytest.raises(RestoreError):
            restore_backup(backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, disk_free=lambda _p: 10 * 1024**3)

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on corrupt zstd"

    def test_corrupt_zip_cleans_tmp_and_aborts(self, tmp_path: Path) -> None:
        # GIVEN a garbage zip archive and existing saves
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.zip"
        backup_path.write_bytes(b"this is not a zip file")
        tmp_dir = tmp_path / "saves-restore-tmp"

        # WHEN restoring the corrupt archive with the real extractor
        with pytest.raises(RestoreError):
            restore_backup(backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, disk_free=lambda _p: 10 * 1024**3)

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on corrupt zip"
