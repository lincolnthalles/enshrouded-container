"""Filesystem operations shared by install, backup, and restore flows — sizes, free space, ownership, atomic writes."""

import os
import shutil
import tempfile
from os import chown
from pathlib import Path


def read_tree_size(target_dir: Path) -> int:
    if target_dir.is_symlink() or not target_dir.exists():
        return 0
    return sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file() and not f.is_symlink())


def disk_free_bytes(path: Path) -> int:
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    return shutil.disk_usage(target).free


def chown_tree(*paths: Path, uid: int, gid: int) -> None:
    first_error: OSError | None = None
    for path in paths:
        try:
            chown(path, uid, gid, follow_symlinks=False)
        except OSError as e:
            if first_error is None:
                first_error = e
        if path.is_symlink():
            continue
        for root, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                try:
                    chown(Path(root) / name, uid, gid, follow_symlinks=False)
                except OSError as e:
                    if first_error is None:
                        first_error = e
    if first_error is not None:
        raise first_error


def write_bytes_atomic(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        tmp_path.chmod(0o644)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)
