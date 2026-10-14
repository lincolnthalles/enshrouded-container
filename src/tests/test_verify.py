"""Tests for verify command."""

import gzip
import tarfile
import zipfile
from dataclasses import replace
from typing import TYPE_CHECKING

from enshctl.backup import verify_archive
from enshctl.backup.catalog import scan_stray

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_tar_zst(path: Path, content: bytes = b"test data") -> None:
    import zstandard

    cctx = zstandard.ZstdCompressor(level=1)
    with (
        path.open("wb") as f_out,
        cctx.stream_writer(f_out) as compressor,
        tarfile.open(fileobj=compressor, mode="w|") as tar,
    ):
        info = tarfile.TarInfo(name="test.txt")
        info.size = len(content)
        tar.addfile(info, fileobj=__import__("io").BytesIO(content))


def _make_tar_gz(path: Path, content: bytes = b"test data") -> None:
    with (
        path.open("wb") as f_out,
        gzip.GzipFile(fileobj=f_out, mode="wb") as gz,
        tarfile.open(fileobj=gz, mode="w|") as tar,
    ):
        info = tarfile.TarInfo(name="test.txt")
        info.size = len(content)
        tar.addfile(info, fileobj=__import__("io").BytesIO(content))


def _make_zip(path: Path, content: bytes = b"test data") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("test.txt", content)


def test_verify_zstd_ok(tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.zst"
    _make_tar_zst(archive)
    assert verify_archive(archive) is True


def test_verify_gzip_ok(tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.gz"
    _make_tar_gz(archive)
    assert verify_archive(archive) is True


def test_verify_zip_ok(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    _make_zip(archive)
    assert verify_archive(archive) is True


def test_verify_corrupt_file(tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.zst"
    archive.write_bytes(b"corrupt data")
    assert verify_archive(archive) is False


def test_verify_empty_file(tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.zst"
    archive.write_bytes(b"")
    assert verify_archive(archive) is False


def test_verify_zip_corrupt_member(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("test.txt", b"hello")
    # Truncate the file to corrupt it
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])
    assert verify_archive(archive) is False


def test_verify_zstd_with_large_content(tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.zst"
    content = b"x" * 100000
    _make_tar_zst(archive, content)
    assert verify_archive(archive) is True


def test_scan_stray_lists_non_grammar_archives(tmp_path: Path) -> None:
    # GIVEN a category dir with a grammar backup, a stray archive, and a stray non-archive
    live = tmp_path / "live"
    live.mkdir()
    (live / "enshrouded-20260529-120000.tar.zst").write_bytes(b"\x00" * 10)
    (live / "manual-copy.zip").write_bytes(b"junk")
    (live / "notes.txt").write_bytes(b"junk")
    # WHEN scanning for strays
    # THEN only the archive-suffixed non-grammar file returns
    assert scan_stray(tmp_path) == [live / "manual-copy.zip"]


def test_scan_stray_missing_dir(tmp_path: Path) -> None:
    # GIVEN a nonexistent base directory
    # WHEN scanning for strays
    # THEN the result is empty
    assert scan_stray(tmp_path / "nonexistent") == []


class TestVerifyAllStrayReporting:
    """Tests for verify --all stray-archive reporting."""

    def test_stray_skipped_with_warning_and_count(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from unittest.mock import patch

        from enshctl.commands import verify as verify_cmd
        from enshctl.settings import AppSettings

        # GIVEN one valid grammar backup plus one stray archive
        live = tmp_path / "live"
        live.mkdir()
        good = live / "enshrouded-20260529-120000.tar.zst"
        _make_tar_zst(good)
        (live / "manual-copy.zip").write_bytes(b"junk")
        settings = replace(AppSettings(), backup_dir=str(tmp_path))

        # WHEN verifying all
        with (
            patch("sys.argv", ["prog"]),
            patch.object(verify_cmd, "load_settings", return_value=settings),
            patch.object(verify_cmd.sys, "exit") as mock_exit,
            caplog.at_level("INFO"),
        ):
            verify_cmd.run()

        # THEN the stray is warned about with a skipped count, exit reflects verified archives only
        warnings = [r for r in caplog.records if r.levelno == 30 and "manual-copy.zip" in r.message]
        assert len(warnings) == 1
        assert any("Skipped 1" in r.message for r in caplog.records)
        mock_exit.assert_called_once_with(0)

    def test_only_strays_exits_zero(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from unittest.mock import patch

        from enshctl.commands import verify as verify_cmd
        from enshctl.settings import AppSettings

        # GIVEN only a stray archive and no grammar backups
        live = tmp_path / "live"
        live.mkdir()
        (live / "manual-copy.zip").write_bytes(b"junk")
        settings = replace(AppSettings(), backup_dir=str(tmp_path))

        # WHEN verifying all
        with (
            patch("sys.argv", ["prog"]),
            patch.object(verify_cmd, "load_settings", return_value=settings),
            patch.object(verify_cmd.sys, "exit") as mock_exit,
            caplog.at_level("INFO"),
        ):
            verify_cmd.run()

        # THEN exit is 0 with a skipped count reported
        mock_exit.assert_not_called()
        assert any("Skipped 1" in r.message for r in caplog.records)
        assert any("No backups to verify" in r.message for r in caplog.records)

    def test_corrupt_verified_still_exits_one(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from enshctl.commands import verify as verify_cmd
        from enshctl.settings import AppSettings

        # GIVEN a corrupt grammar backup plus a stray archive
        live = tmp_path / "live"
        live.mkdir()
        (live / "enshrouded-20260529-120000.tar.zst").write_bytes(b"corrupt data")
        (live / "manual-copy.zip").write_bytes(b"junk")
        settings = replace(AppSettings(), backup_dir=str(tmp_path))

        # WHEN verifying all
        with (
            patch("sys.argv", ["prog"]),
            patch.object(verify_cmd, "load_settings", return_value=settings),
            patch.object(verify_cmd.sys, "exit") as mock_exit,
        ):
            verify_cmd.run()

        # THEN the corrupt verified archive drives exit 1
        mock_exit.assert_called_once_with(1)

    def test_verify_file_accepts_stray_name(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from enshctl.commands import verify as verify_cmd
        from enshctl.settings import AppSettings

        # GIVEN a stray archive addressable by filename
        live = tmp_path / "live"
        live.mkdir()
        stray = live / "manual-copy.zip"
        _make_zip(stray)
        settings = replace(AppSettings(), backup_dir=str(tmp_path))

        # WHEN verifying that specific file
        with (
            patch("sys.argv", ["prog", "--file", "manual-copy.zip"]),
            patch.object(verify_cmd, "load_settings", return_value=settings),
            patch.object(verify_cmd.sys, "exit") as mock_exit,
        ):
            verify_cmd.run()

        # THEN it verifies OK instead of reporting not found
        mock_exit.assert_called_once_with(0)
