"""Filesystem probes shared by install, backup, and restore flows — sizes, free space, ownership."""

import shutil
from os import chown
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    for path in paths:
        chown(path, uid, gid)
