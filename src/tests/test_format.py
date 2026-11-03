"""Tests for the Backup format module."""

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from enshctl.backup.format import ArchiveError, BackupFormat, decompress_archive, detect_format, verify_archive

if TYPE_CHECKING:
    from collections.abc import Callable


def _source_tree(tmp_path: Path) -> Path:
    source = tmp_path / "saves"
    source.mkdir()
    (source / "world.db").write_bytes(b"world")
    nested = source / "nested"
    nested.mkdir()
    (nested / "extra.dat").write_bytes(b"extra")
    return source


def _corrupt_zip_payload(archive: Path) -> None:
    data = bytearray(archive.read_bytes())
    local = data.find(b"PK\x03\x04")
    name_len = int.from_bytes(data[local + 26 : local + 28], "little")
    extra_len = int.from_bytes(data[local + 28 : local + 30], "little")
    payload_start = local + 30 + name_len + extra_len
    data[payload_start] ^= 0xFF
    archive.write_bytes(bytes(data))


def _mark_zip_encrypted(archive: Path) -> None:
    data = bytearray(archive.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    for offset in (local + 6, central + 8):
        flags = int.from_bytes(data[offset : offset + 2], "little") | 0x1
        data[offset : offset + 2] = flags.to_bytes(2, "little")
    archive.write_bytes(bytes(data))


def _mark_zip_unsupported(archive: Path) -> None:
    data = bytearray(archive.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    for offset in (local + 8, central + 10):
        data[offset : offset + 2] = (42).to_bytes(2, "little")
    archive.write_bytes(bytes(data))


def test_backup_format_zstd() -> None:
    fmt = BackupFormat.ZSTD
    assert fmt.get_extension() == ".tar.zst"
    assert fmt.get_max_level() == 22
    assert fmt.clamp_level(19) == 19
    assert fmt.clamp_level(25) == 22
    assert fmt.clamp_level(0) == 0


def test_backup_format_gzip() -> None:
    fmt = BackupFormat.GZIP
    assert fmt.get_extension() == ".tar.gz"
    assert fmt.get_max_level() == 9
    assert fmt.clamp_level(9) == 9
    assert fmt.clamp_level(15) == 9
    assert fmt.clamp_level(0) == 0


def test_backup_format_zip() -> None:
    fmt = BackupFormat.ZIP
    assert fmt.get_extension() == ".zip"
    assert fmt.get_max_level() == 9
    assert fmt.clamp_level(3) == 3
    assert fmt.clamp_level(12) == 9


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_detect_format_recognizes_extension(fmt: BackupFormat) -> None:
    # GIVEN a filename with the format's extension
    # WHEN detecting the format
    # THEN the matching format is returned
    assert detect_format(Path(f"backup{fmt.get_extension()}")) == fmt


def test_detect_format_rejects_unknown_extension() -> None:
    # GIVEN a filename with no known extension
    # WHEN detecting the format
    # THEN detection fails
    with pytest.raises(ValueError, match="Cannot detect"):
        detect_format(Path("backup.bin"))


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_compress_decompress_round_trip(tmp_path: Path, fmt: BackupFormat) -> None:
    # GIVEN a source tree
    source = _source_tree(tmp_path)
    archive = tmp_path / f"backup{fmt.get_extension()}"
    target = tmp_path / "restored"
    target.mkdir()

    # WHEN compressing and decompressing
    fmt.compress(source, archive, 1)
    decompress_archive(archive, target)

    # THEN every file round-trips and the archive verifies
    assert (target / "world.db").read_bytes() == b"world"
    assert (target / "nested" / "extra.dat").read_bytes() == b"extra"
    assert verify_archive(archive) is True


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_compress_failure_raises_archive_error(tmp_path: Path, fmt: BackupFormat) -> None:
    # GIVEN a source tree and an output path whose parent is a file
    source = _source_tree(tmp_path)
    parent = tmp_path / "not-a-dir"
    parent.write_text("x")

    # WHEN compressing
    # THEN the failure uses the archive contract
    with pytest.raises(ArchiveError):
        fmt.compress(source, parent / f"backup{fmt.get_extension()}", 1)


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_verify_rejects_corrupt_archive(tmp_path: Path, fmt: BackupFormat) -> None:
    # GIVEN a file with a known extension but invalid content
    archive = tmp_path / f"corrupt{fmt.get_extension()}"
    archive.write_bytes(b"not an archive")

    # WHEN verifying
    # THEN it reports corrupt
    assert verify_archive(archive) is False


def test_verify_rejects_zip_with_corrupt_payload(tmp_path: Path) -> None:
    # GIVEN a zip with an intact directory but a corrupt member payload
    archive = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("world.db", b"world" * 100)
    _corrupt_zip_payload(archive)

    # WHEN verifying
    # THEN it reports corrupt instead of raising
    assert verify_archive(archive) is False


def test_decompress_zip_with_corrupt_payload_raises_archive_error(tmp_path: Path) -> None:
    # GIVEN a zip with an intact directory but a corrupt member payload
    archive = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("world.db", b"world" * 100)
    _corrupt_zip_payload(archive)
    target = tmp_path / "out"
    target.mkdir()

    # WHEN decompressing
    # THEN the failure uses the archive contract
    with pytest.raises(ArchiveError):
        decompress_archive(archive, target)


@pytest.mark.parametrize(
    "mutator",
    [_mark_zip_encrypted, _mark_zip_unsupported],
    ids=["encrypted", "unsupported"],
)
def test_zip_read_failures_use_archive_contract(tmp_path: Path, mutator: Callable[[Path], None]) -> None:
    # GIVEN a zip whose member cannot be read by zipfile
    archive = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("world.db", b"world")
    mutator(archive)
    target = tmp_path / "out"
    target.mkdir()

    # WHEN verifying and decompressing
    # THEN both use the archive contract
    assert verify_archive(archive) is False
    with pytest.raises(ArchiveError):
        decompress_archive(archive, target)


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_verify_rejects_empty_archive(tmp_path: Path, fmt: BackupFormat) -> None:
    # GIVEN an empty file with a known extension
    archive = tmp_path / f"empty{fmt.get_extension()}"
    archive.touch()

    # WHEN verifying
    # THEN it reports corrupt
    assert verify_archive(archive) is False


def test_verify_zstd_with_large_content(tmp_path: Path) -> None:
    # GIVEN a zstd archive containing a file larger than the verify chunk
    source = tmp_path / "saves"
    source.mkdir()
    (source / "world.db").write_bytes(b"x" * 100_000)
    archive = tmp_path / "backup.tar.zst"
    BackupFormat.ZSTD.compress(source, archive, 1)

    # WHEN verifying
    # THEN the whole stream is read successfully
    assert verify_archive(archive) is True


def test_verify_unknown_suffix_reports_corrupt(tmp_path: Path) -> None:
    # GIVEN a file whose suffix matches no format
    archive = tmp_path / "backup.bin"
    archive.write_bytes(b"not an archive")

    # WHEN verifying
    # THEN it reports corrupt
    assert verify_archive(archive) is False


def test_decompress_unknown_suffix_raises_archive_error(tmp_path: Path) -> None:
    # GIVEN a file whose suffix matches no format
    archive = tmp_path / "backup.bin"
    archive.write_bytes(b"not an archive")
    target = tmp_path / "out"
    target.mkdir()

    # WHEN decompressing
    # THEN the failure uses the archive contract
    with pytest.raises(ArchiveError, match="Cannot detect"):
        decompress_archive(archive, target)


@pytest.mark.parametrize("fmt", list(BackupFormat))
def test_decompress_corrupt_archive_raises_archive_error(tmp_path: Path, fmt: BackupFormat) -> None:
    # GIVEN a file with a known extension but invalid content
    archive = tmp_path / f"corrupt{fmt.get_extension()}"
    archive.write_bytes(b"not an archive")
    target = tmp_path / "out"
    target.mkdir()

    # WHEN decompressing
    # THEN the failure uses the archive contract
    with pytest.raises(ArchiveError):
        decompress_archive(archive, target)
