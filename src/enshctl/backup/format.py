"""Backup format registry — one home for extensions, levels, detection, and archive operations."""

import gzip
import logging
import tarfile
import zipfile
import zlib
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import zstandard

if TYPE_CHECKING:
    from enshctl.backup.excludes import BackupExcludes

logger = logging.getLogger(__name__)


class ArchiveError(Exception):
    """Raised for expected archive-format and I/O failures.

    Compression value errors are deliberately not handled here; they propagate
    so the backup run reports an error.
    """


_ARCHIVE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    EOFError,
    tarfile.TarError,
    zstandard.ZstdError,
    zipfile.BadZipFile,
    zlib.error,
)

_READ_ERRORS: tuple[type[BaseException], ...] = (
    *_ARCHIVE_ERRORS,
    ValueError,
    RuntimeError,
    NotImplementedError,
)

_CHUNK = 65536


def _extract_tar(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Extract tar members, stripping 'saves/' prefix from old archives."""
    for member in tar:
        member.name = member.name.removeprefix("saves/")
        if not member.name:
            continue
        tar.extract(member, path=str(target_dir))


def _verify_tar_stream(tar: tarfile.TarFile) -> None:
    """Read every member's data to EOF to verify archive integrity."""
    for member in tar:
        if member.isfile():
            f = tar.extractfile(member)
            if f:
                while f.read(_CHUNK):
                    pass


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

    def compress(
        self,
        source_dir: Path,
        output_path: Path,
        level: int,
        *,
        excludes: BackupExcludes | None = None,
    ) -> None:
        excluded_count = 0

        def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
            nonlocal excluded_count
            if excludes is not None and excludes.is_excluded(info.name):
                excluded_count += 1
                return None
            return info

        try:
            match self:
                case BackupFormat.ZSTD:
                    cctx = zstandard.ZstdCompressor(level=level)
                    logger.info("Creating zstd backup at level %d", level)
                    with (
                        output_path.open("wb") as f_out,
                        cctx.stream_writer(f_out) as compressor,
                        tarfile.open(fileobj=compressor, mode="w|") as tar,
                    ):
                        tar.add(str(source_dir), arcname=".", filter=_tar_filter)
                case BackupFormat.GZIP:
                    logger.info("Creating gzip backup at level %d", level)
                    with (
                        output_path.open("wb") as f_out,
                        gzip.GzipFile(fileobj=f_out, mode="wb", compresslevel=level) as gz,
                        tarfile.open(fileobj=gz, mode="w|") as tar,
                    ):
                        tar.add(str(source_dir), arcname=".", filter=_tar_filter)
                case BackupFormat.ZIP:
                    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
                        for file_path in source_dir.rglob("*"):
                            if file_path.is_file():
                                arcname = str(file_path.relative_to(source_dir))
                                if excludes is not None and excludes.is_excluded(arcname):
                                    excluded_count += 1
                                    continue
                                zf.write(file_path, arcname)
        except _ARCHIVE_ERRORS as exc:
            msg = f"{self.value} compression failed: {exc}"
            raise ArchiveError(msg) from exc
        if excluded_count:
            logger.info("Excluded %d path(s) via BACKUP_EXCLUDE", excluded_count)

    def decompress(self, archive_path: Path, target_dir: Path) -> None:
        try:
            match self:
                case BackupFormat.ZSTD:
                    dctx = zstandard.ZstdDecompressor()
                    with (
                        archive_path.open("rb") as f_in,
                        dctx.stream_reader(f_in) as decompressor,
                        tarfile.open(fileobj=decompressor, mode="r|") as tar,
                    ):
                        _extract_tar(tar, target_dir)
                case BackupFormat.GZIP:
                    with (
                        archive_path.open("rb") as f_in,
                        gzip.GzipFile(fileobj=f_in, mode="rb") as gz,
                        tarfile.open(fileobj=gz, mode="r|") as tar,
                    ):
                        _extract_tar(tar, target_dir)
                case BackupFormat.ZIP:
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        for info in zf.infolist():
                            info.filename = info.filename.removeprefix("saves/")
                            if not info.filename:
                                continue
                            zf.extract(info, path=str(target_dir))
        except _READ_ERRORS as exc:
            msg = f"{self.value} extraction failed: {exc}"
            raise ArchiveError(msg) from exc

    def verify(self, archive_path: Path) -> bool:
        try:
            match self:
                case BackupFormat.ZSTD:
                    dctx = zstandard.ZstdDecompressor()
                    with (
                        archive_path.open("rb") as f_in,
                        dctx.stream_reader(f_in) as reader,
                        tarfile.open(fileobj=reader, mode="r|") as tar,
                    ):
                        _verify_tar_stream(tar)
                    return True
                case BackupFormat.GZIP:
                    with (
                        archive_path.open("rb") as f_in,
                        gzip.GzipFile(fileobj=f_in, mode="rb") as gz,
                        tarfile.open(fileobj=gz, mode="r|") as tar,
                    ):
                        _verify_tar_stream(tar)
                    return True
                case BackupFormat.ZIP:
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        bad = zf.testzip()
                        if bad is not None:
                            logger.warning("Zip verification failed for member: %s", bad)
                            return False
                    return True
        except _READ_ERRORS as exc:
            logger.warning("Verification failed for %s: %s", archive_path, exc)
            return False


ARCHIVE_EXTENSIONS: tuple[str, ...] = tuple(fmt.get_extension() for fmt in BackupFormat)
ARCHIVE_SUFFIXES: tuple[str, ...] = tuple(
    dict.fromkeys(f".{extension.rsplit('.', 1)[-1]}" for extension in ARCHIVE_EXTENSIONS)
)

_EXTENSION_MAP: dict[str, BackupFormat] = {fmt.get_extension(): fmt for fmt in BackupFormat}


def detect_format(path: Path) -> BackupFormat:
    name = path.name
    for ext_str, fmt in _EXTENSION_MAP.items():
        if name.endswith(ext_str):
            return fmt
    msg = f"Cannot detect backup format for {path}"
    raise ValueError(msg)


def decompress_archive(archive_path: Path, target_dir: Path) -> None:
    """Extract a Backup archive, raising ArchiveError when it cannot be read."""
    try:
        fmt = detect_format(archive_path)
    except ValueError as exc:
        raise ArchiveError(str(exc)) from exc
    fmt.decompress(archive_path, target_dir)


def verify_archive(archive_path: Path) -> bool:
    """Stream all members to EOF to verify archive integrity.

    Returns True if intact, False if corrupt.
    """
    try:
        fmt = detect_format(archive_path)
    except ValueError as exc:
        logger.warning("Verification failed for %s: %s", archive_path, exc)
        return False
    return fmt.verify(archive_path)
