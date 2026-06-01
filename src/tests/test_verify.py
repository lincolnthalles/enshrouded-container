"""Tests for verify command."""

import gzip
import tarfile
import zipfile
from typing import TYPE_CHECKING

from enshctl.backup import verify_archive

if TYPE_CHECKING:
    from pathlib import Path


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
