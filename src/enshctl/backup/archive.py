"""Archive compression, decompression, and verification."""

import gzip
import logging
import tarfile
import zipfile
from typing import TYPE_CHECKING

import zstandard

from enshctl.backup.core import _FORMAT_EXTENSION_MAP, BackupFormat

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK = 65536


def _compress_zstd(source_dir: Path, output_path: Path, level: int) -> None:
    cctx = zstandard.ZstdCompressor(level=level)
    logger.info("Creating zstd backup at level %d", level)
    with (
        output_path.open("wb") as f_out,
        cctx.stream_writer(f_out) as compressor,
        tarfile.open(fileobj=compressor, mode="w|") as tar,
    ):
        tar.add(str(source_dir), arcname=".")


def _compress_gzip(source_dir: Path, output_path: Path, level: int) -> None:
    logger.info("Creating gzip backup at level %d", level)
    with (
        output_path.open("wb") as f_out,
        gzip.GzipFile(fileobj=f_out, mode="wb", compresslevel=level) as gz,
        tarfile.open(fileobj=gz, mode="w|") as tar,
    ):
        tar.add(str(source_dir), arcname=".")


def _compress_zip(source_dir: Path, output_path: Path, level: int) -> None:
    logger.info("Creating zip backup at level %d", level)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(file_path.relative_to(source_dir))
                zf.write(file_path, arcname)


def decompress_archive(archive_path: Path, target_dir: Path) -> None:
    fmt = _detect_format(archive_path)
    match fmt:
        case BackupFormat.ZSTD:
            _decompress_zstd(archive_path, target_dir)
        case BackupFormat.GZIP:
            _decompress_gzip(archive_path, target_dir)
        case BackupFormat.ZIP:
            _decompress_zip(archive_path, target_dir)


def _detect_format(path: Path) -> BackupFormat:
    name = path.name
    for ext_str, fmt in _FORMAT_EXTENSION_MAP.items():
        if name.endswith(ext_str):
            return fmt
    msg = f"Cannot detect backup format for {path}"
    raise ValueError(msg)


def _decompress_zstd(archive_path: Path, target_dir: Path) -> None:
    dctx = zstandard.ZstdDecompressor()
    with (
        archive_path.open("rb") as f_in,
        dctx.stream_reader(f_in) as decompressor,
        tarfile.open(fileobj=decompressor, mode="r|") as tar,
    ):
        _extract_tar(tar, target_dir)


def _decompress_gzip(archive_path: Path, target_dir: Path) -> None:
    with (
        archive_path.open("rb") as f_in,
        gzip.GzipFile(fileobj=f_in, mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r|") as tar,
    ):
        _extract_tar(tar, target_dir)


def _extract_tar(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Extract tar members, stripping 'saves/' prefix from old archives."""
    for member in tar:
        member.name = member.name.removeprefix("saves/")
        if not member.name:
            continue
        tar.extract(member, path=str(target_dir))


def _decompress_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            info.filename = info.filename.removeprefix("saves/")
            if not info.filename:
                continue
            zf.extract(info, path=str(target_dir))


def verify_archive(archive_path: Path) -> bool:
    """Stream all members to EOF to verify archive integrity.

    Returns True if intact, False if corrupt.
    """
    fmt = _detect_format(archive_path)
    try:
        match fmt:
            case BackupFormat.ZSTD:
                return _verify_zstd(archive_path)
            case BackupFormat.GZIP:
                return _verify_gzip(archive_path)
            case BackupFormat.ZIP:
                return _verify_zip(archive_path)
    except (OSError, EOFError, tarfile.TarError, zstandard.ZstdError, zipfile.BadZipFile) as exc:
        logger.warning("Verification failed for %s: %s", archive_path, exc)
        return False


def _verify_tar_stream(tar: tarfile.TarFile) -> None:
    """Read every member's data to EOF to verify archive integrity."""
    for member in tar:
        if member.isfile():
            f = tar.extractfile(member)
            if f:
                while f.read(_CHUNK):
                    pass


def _verify_zstd(path: Path) -> bool:
    dctx = zstandard.ZstdDecompressor()
    with path.open("rb") as f_in, dctx.stream_reader(f_in) as reader, tarfile.open(fileobj=reader, mode="r|") as tar:
        _verify_tar_stream(tar)
    return True


def _verify_gzip(path: Path) -> bool:
    with (
        path.open("rb") as f_in,
        gzip.GzipFile(fileobj=f_in, mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r|") as tar,
    ):
        _verify_tar_stream(tar)
    return True


def _verify_zip(path: Path) -> bool:
    with zipfile.ZipFile(path, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            logger.warning("Zip verification failed for member: %s", bad)
            return False
    return True
