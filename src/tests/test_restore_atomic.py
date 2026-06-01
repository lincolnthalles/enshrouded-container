"""Tests for restore atomic swap (extract-to-tmp then move)."""

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path


class TestRestoreAtomicSwap:
    """Tests for the restore atomic swap pattern."""

    def test_successful_restore_uses_tmp_then_swaps(self, tmp_path: Path) -> None:
        from enshctl.commands.restore import run

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")

        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        tmp_dir = tmp_path / "saves-restore-tmp"

        def _fake_extract(_src: Path, dst: Path) -> None:
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "new_save.db").write_bytes(b"new")

        with (
            patch("sys.argv", ["prog", "--file", "backup.tar.zst", "--yes"]),
            patch("enshctl.commands.restore.SAVE_DIR", saves_dir),
            patch("enshctl.commands.restore.RESTORE_TMP_DIR", tmp_dir),
            patch("enshctl.commands.restore.select_backup", return_value=backup_path),
            patch("enshctl.commands.restore._check_server_running", return_value=False),
            patch("enshctl.commands.restore._confirm_restore", return_value=True),
            patch("enshctl.commands.restore.acquire_lock", return_value=3),
            patch("enshctl.commands.restore.decompress_archive", side_effect=_fake_extract),
            patch("enshctl.commands.restore.shutil.disk_usage") as mock_du,
            patch("enshctl.commands.restore.release_lock"),
        ):
            mock_du.return_value.free = 10 * 1024**3
            run()

        assert not tmp_dir.exists(), "tmp directory should be removed"
        assert (saves_dir / "new_save.db").read_bytes() == b"new"
        assert not (saves_dir / "old_save.db").exists(), "old saves should be gone"

    def test_extraction_failure_leaves_saves_untouched(self, tmp_path: Path) -> None:
        from enshctl.commands.restore import run

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")

        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        tmp_dir = tmp_path / "saves-restore-tmp"

        with (
            patch("sys.argv", ["prog", "--file", "backup.tar.zst", "--yes"]),
            patch("enshctl.commands.restore.SAVE_DIR", saves_dir),
            patch("enshctl.commands.restore.RESTORE_TMP_DIR", tmp_dir),
            patch("enshctl.commands.restore.select_backup", return_value=backup_path),
            patch("enshctl.commands.restore._check_server_running", return_value=False),
            patch("enshctl.commands.restore._confirm_restore", return_value=True),
            patch("enshctl.commands.restore.acquire_lock", return_value=3),
            patch("enshctl.commands.restore.decompress_archive", side_effect=OSError("ENOSPC")),
            patch("enshctl.commands.restore.shutil.disk_usage") as mock_du,
            patch("enshctl.commands.restore.release_lock"),
            patch("enshctl.commands.restore.sys.exit") as mock_exit,
        ):
            mock_du.return_value.free = 0
            run()
            mock_exit.assert_called_once_with(1)

        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on failure"

    def test_space_check_failure_cleans_tmp_and_aborts(self, tmp_path: Path) -> None:
        from enshctl.commands.restore import run

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")

        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        tmp_dir = tmp_path / "saves-restore-tmp"

        def _fake_extract(_src: Path, dst: Path) -> None:
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "bigger_file.db").write_bytes(b"bigger")

        with (
            patch("sys.argv", ["prog", "--file", "backup.tar.zst", "--yes"]),
            patch("enshctl.commands.restore.SAVE_DIR", saves_dir),
            patch("enshctl.commands.restore.RESTORE_TMP_DIR", tmp_dir),
            patch("enshctl.commands.restore.select_backup", return_value=backup_path),
            patch("enshctl.commands.restore._check_server_running", return_value=False),
            patch("enshctl.commands.restore._confirm_restore", return_value=True),
            patch("enshctl.commands.restore.acquire_lock", return_value=3),
            patch("enshctl.commands.restore.decompress_archive", side_effect=_fake_extract),
            patch("enshctl.commands.restore.shutil.disk_usage") as mock_du,
            patch("enshctl.commands.restore.release_lock"),
            patch("enshctl.commands.restore.sys.exit") as mock_exit,
        ):
            mock_du.return_value.free = 0
            run()
            mock_exit.assert_called_once_with(1)

        assert (saves_dir / "old_save.db").read_bytes() == b"old"
        assert not tmp_dir.exists(), "tmp should be cleaned up on space check failure"

    def test_pre_existing_tmp_removed_before_extract(self, tmp_path: Path) -> None:
        from enshctl.commands.restore import run

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir()
        (saves_dir / "old_save.db").write_bytes(b"old")

        backup_path = tmp_path / "backup.tar.zst"
        backup_path.write_bytes(b"")

        tmp_dir = tmp_path / "saves-restore-tmp"
        tmp_dir.mkdir()
        (tmp_dir / "stale_file.tmp").write_bytes(b"stale")

        def _fake_extract(_src: Path, dst: Path) -> None:
            assert (tmp_dir / "stale_file.tmp").exists() is False, "stale file should be removed first"
            (dst / "new_save.db").write_bytes(b"new")

        with (
            patch("sys.argv", ["prog", "--file", "backup.tar.zst", "--yes"]),
            patch("enshctl.commands.restore.SAVE_DIR", saves_dir),
            patch("enshctl.commands.restore.RESTORE_TMP_DIR", tmp_dir),
            patch("enshctl.commands.restore.select_backup", return_value=backup_path),
            patch("enshctl.commands.restore._check_server_running", return_value=False),
            patch("enshctl.commands.restore._confirm_restore", return_value=True),
            patch("enshctl.commands.restore.acquire_lock", return_value=3),
            patch("enshctl.commands.restore.decompress_archive", side_effect=_fake_extract),
            patch("enshctl.commands.restore.shutil.disk_usage") as mock_du,
            patch("enshctl.commands.restore.release_lock"),
        ):
            mock_du.return_value.free = 10 * 1024**3
            run()
