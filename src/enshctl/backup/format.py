"""Backup format registry — one home for extensions, levels, and archive operations."""

import gzip
import logging
import tarfile
import zipfile
from enum import Enum
from typing import TYPE_CHECKING

import zstandard

from enshctl.paths import (
    BACKUP_DIR_COLD,
    BACKUP_DIR_EMERGENCY,
    BACKUP_DIR_LIVE,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

ARCHIVE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    EOFError,
    tarfile.TarError,
    zstandard.ZstdError,
    zipfile.BadZipFile,
)

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
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(file_path.relative_to(source_dir))
                zf.write(file_path, arcname)


def _extract_tar(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Extract tar members, stripping 'saves/' prefix from old archives."""
    for member in tar:
        member.name = member.name.removeprefix("saves/")
        if not member.name:
            continue
        tar.extract(member, path=str(target_dir))


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


def _decompress_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            info.filename = info.filename.removeprefix("saves/")
            if not info.filename:
                continue
            zf.extract(info, path=str(target_dir))


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


class BackupFormat(Enum):
    ZSTD = "zstd"
    GZIP = "gzip"
    ZIP = "zip"

    def get_extension(self) -> str:
        match self:
            case BackupFormat.ZSTD:
                return ".tar.zst"
            case BackupFormat.GZIP:
                return ".tar.gz"
            case BackupFormat.ZIP:
                return ".zip"

    def get_max_level(self) -> int:
        match self:
            case BackupFormat.ZSTD:
                return 22
            case BackupFormat.GZIP:
                return 9
            case BackupFormat.ZIP:
                return 9

    def clamp_level(self, level: int) -> int:
        max_level = self.get_max_level()
        if level > max_level:
            logger.warning(
                "Compression level %d exceeds %s max (%d), clamping to %d", level, self.value, max_level, max_level
            )
            return max_level
        return level

    def get_default_level(self) -> int:
        match self:
            case BackupFormat.ZSTD:
                return 9
            case BackupFormat.GZIP:
                return 6
            case BackupFormat.ZIP:
                return 6

    def compress(self) -> Callable[[Path, Path, int], None]:
        match self:
            case BackupFormat.ZSTD:
                return _compress_zstd
            case BackupFormat.GZIP:
                return _compress_gzip
            case BackupFormat.ZIP:
                return _compress_zip

    def decompress(self) -> Callable[[Path, Path], None]:
        match self:
            case BackupFormat.ZSTD:
                return _decompress_zstd
            case BackupFormat.GZIP:
                return _decompress_gzip
            case BackupFormat.ZIP:
                return _decompress_zip

    def verify(self) -> Callable[[Path], bool]:
        match self:
            case BackupFormat.ZSTD:
                return _verify_zstd
            case BackupFormat.GZIP:
                return _verify_gzip
            case BackupFormat.ZIP:
                return _verify_zip


_EXTENSION_MAP: dict[str, BackupFormat] = {fmt.get_extension(): fmt for fmt in BackupFormat}


def detect_format(path: Path) -> BackupFormat:
    name = path.name
    for ext_str, fmt in _EXTENSION_MAP.items():
        if name.endswith(ext_str):
            return fmt
    msg = f"Cannot detect backup format for {path}"
    raise ValueError(msg)


def category_suffix(category: str) -> str:
    if category == BACKUP_DIR_COLD:
        return "-cold"
    if category == BACKUP_DIR_EMERGENCY:
        return "-emergency"
    return ""


def suffix_category(suffix: str) -> str:
    if suffix == "-cold":
        return BACKUP_DIR_COLD
    if suffix == "-emergency":
        return BACKUP_DIR_EMERGENCY
    return BACKUP_DIR_LIVE
