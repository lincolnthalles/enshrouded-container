"""Tests for restore atomic swap (extract-to-tmp then move)."""

from typing import TYPE_CHECKING

import pytest
from enshctl.backup import ArchiveError
from enshctl.disk_space import SpaceGuard
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
            backup_path,
            saves_dir=saves_dir,
            tmp_dir=tmp_dir,
            extract=_extract_new,
            space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3),
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
            raise ArchiveError(msg)

        # WHEN restoring
        with pytest.raises(RestoreError):
            restore_backup(
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=tmp_dir,
                extract=_fail,
                space=SpaceGuard(disk_free=lambda _p: 0),
            )

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
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=tmp_dir,
                extract=_extract_bigger,
                space=SpaceGuard(disk_free=lambda _p: 0),
            )

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on space check failure"

    def test_missing_saves_dir_is_created_and_restored(self, tmp_path: Path) -> None:
        # GIVEN a configured saves path whose parent directories do not exist
        saves_dir = tmp_path / "nested" / "saves"
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = saves_dir.parent / "saves-restore-tmp"

        # WHEN restoring with ample free space
        restore_backup(
            backup_path,
            saves_dir=saves_dir,
            tmp_dir=tmp_dir,
            extract=_extract_new,
            space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3),
        )

        # THEN the saves directory is created and populated
        assert (saves_dir / "new_save.db").read_bytes() == b"new"
        assert not tmp_dir.exists()

    def test_space_failure_removes_created_empty_saves_dir(self, tmp_path: Path) -> None:
        # GIVEN a missing saves directory and no free space
        saves_dir = tmp_path / "nested" / "saves"
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = saves_dir.parent / "saves-restore-tmp"

        def _extract_bigger(_src: Path, dst: Path) -> None:
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "bigger_file.db").write_bytes(b"bigger")

        # WHEN the space check fails
        with pytest.raises(RestoreError):
            restore_backup(
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=tmp_dir,
                extract=_extract_bigger,
                space=SpaceGuard(disk_free=lambda _p: 0),
            )

        # THEN the temporary directory and the empty created saves directory are removed
        assert not tmp_dir.exists()
        assert not saves_dir.exists()

    def test_space_check_uses_pre_extraction_free_space(self, tmp_path: Path) -> None:
        # GIVEN a same-filesystem temp directory and free space that shrinks during extraction
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"x" * 20)
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"
        state = {"extracted": False}
        free_calls = 0

        def _free(_path: Path) -> int:
            nonlocal free_calls
            free_calls += 1
            return 10 if state["extracted"] else 70

        def _extract_80(_src: Path, dst: Path) -> None:
            state["extracted"] = True
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "new_save.db").write_bytes(b"x" * 80)

        # WHEN restoring with pre-extraction free space covering the extracted data
        restore_backup(
            backup_path,
            saves_dir=saves_dir,
            tmp_dir=tmp_dir,
            extract=_extract_80,
            space=SpaceGuard(disk_free=_free),
        )

        # THEN free space is measured once before extraction
        assert free_calls == 1
        assert (saves_dir / "new_save.db").read_bytes() == b"x" * 80
        assert not tmp_dir.exists()

    def test_tmp_equal_saves_is_rejected(self, tmp_path: Path) -> None:
        # GIVEN a temp path that is the saves directory itself
        saves_dir = tmp_path / "saves-restore-tmp"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        # WHEN restoring
        # THEN the overlap is rejected before any deletion
        with pytest.raises(RestoreError):
            restore_backup(
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=saves_dir,
                space=SpaceGuard(disk_free=lambda _path: 10 * 1024**3),
            )
        assert (saves_dir / "old_save.db").read_bytes() == b"old"

    def test_symlink_in_saves_is_unlinked_not_followed(self, tmp_path: Path) -> None:
        # GIVEN a symlink inside saves pointing at data outside it
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (target / "keep.db").write_bytes(b"keep")
        (saves_dir / "link").symlink_to(target, target_is_directory=True)
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"

        # WHEN restoring
        restore_backup(
            backup_path,
            saves_dir=saves_dir,
            tmp_dir=tmp_dir,
            extract=_extract_new,
            space=SpaceGuard(disk_free=lambda _path: 10 * 1024**3),
        )

        # THEN only the symlink is removed and its target is untouched
        assert not (saves_dir / "link").exists()
        assert (target / "keep.db").read_bytes() == b"keep"

    def test_saves_inside_tmp_is_rejected(self, tmp_path: Path) -> None:
        # GIVEN a temp directory that contains the saves directory
        tmp_dir = tmp_path / "outer"
        saves_dir = tmp_dir / "saves"
        saves_dir.mkdir(parents=True)
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        # WHEN restoring
        # THEN the overlap is rejected before any deletion
        with pytest.raises(RestoreError):
            restore_backup(
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=tmp_dir,
                space=SpaceGuard(disk_free=lambda _path: 10 * 1024**3),
            )
        assert (saves_dir / "old_save.db").read_bytes() == b"old"

    def test_tmp_preparation_failure_is_restore_error(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        # GIVEN a temp directory that cannot be created
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        # WHEN restoring
        with patch("pathlib.Path.mkdir", side_effect=OSError("nope")), pytest.raises(RestoreError):
            # THEN the failure surfaces as RestoreError
            restore_backup(
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=tmp_path / "saves-restore-tmp",
                space=SpaceGuard(disk_free=lambda _path: 10 * 1024**3),
            )

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
            backup_path,
            saves_dir=saves_dir,
            tmp_dir=tmp_dir,
            extract=_extract_fresh,
            space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3),
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
            restore_backup(
                backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3)
            )

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
            restore_backup(
                backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3)
            )

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on corrupt zip"

    def test_unknown_suffix_cleans_tmp_and_aborts(self, tmp_path: Path) -> None:
        # GIVEN a backup whose suffix matches no known format
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.bin"
        backup_path.write_bytes(b"not an archive")
        tmp_dir = tmp_path / "saves-restore-tmp"

        # WHEN restoring the unreadable archive with the real extractor
        with pytest.raises(RestoreError):
            restore_backup(
                backup_path, saves_dir=saves_dir, tmp_dir=tmp_dir, space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3)
            )

        # THEN saves are untouched and tmp is cleaned up
        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on unreadable format"

    def test_swap_failure_cleans_tmp_and_raises(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        # GIVEN extracted data ready but a move that fails mid-swap
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")
        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")
        tmp_dir = tmp_path / "saves-restore-tmp"

        def _fail_move(_src: str, _dst: str) -> None:
            msg = "move failed"
            raise OSError(msg)

        # WHEN the swap move fails
        with (
            patch("enshctl.restore.shutil.move", side_effect=_fail_move),
            pytest.raises(RestoreError),
        ):
            restore_backup(
                backup_path,
                saves_dir=saves_dir,
                tmp_dir=tmp_dir,
                extract=_extract_new,
                space=SpaceGuard(disk_free=lambda _p: 10 * 1024**3),
            )

        # THEN tmp is cleaned up and the failure surfaces as RestoreError
        assert not tmp_dir.exists(), "tmp should be cleaned up on swap failure"
