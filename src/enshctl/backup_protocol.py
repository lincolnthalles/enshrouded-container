"""Backup parent/child protocol — outcome enum and typed request shared across the seam."""

import argparse  # noqa: TC003 — add_arguments builds a real parser at runtime
from dataclasses import dataclass
from enum import IntEnum

from enshctl.paths import BACKUP_DIR_COLD, BACKUP_DIR_EMERGENCY, BACKUP_DIR_LIVE


class BackupOutcome(IntEnum):
    SUCCESS = 0
    LOCK_HELD = 1
    ERROR = 2


@dataclass(frozen=True)
class BackupRequest:
    category: str = BACKUP_DIR_LIVE
    wait_seconds: int = 0
    detach: bool = False

    def to_argv(self) -> list[str]:
        argv: list[str] = []
        if self.category == BACKUP_DIR_COLD:
            argv.append("--cold")
        elif self.category == BACKUP_DIR_EMERGENCY:
            argv.append("--emergency")
        if self.wait_seconds > 0:
            argv.extend(["--wait", str(self.wait_seconds)])
        return argv

    @classmethod
    def from_argv(cls, args: argparse.Namespace) -> BackupRequest:
        category = BACKUP_DIR_LIVE
        if args.cold:
            category = BACKUP_DIR_COLD
        elif args.emergency:
            category = BACKUP_DIR_EMERGENCY
        return cls(category=category, wait_seconds=args.wait)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", default=None, type=str.lower, choices=["zstd", "gzip", "zip"])
    parser.add_argument("--level", type=int, default=None)
    parser.add_argument("--cold", action="store_true", default=False)
    parser.add_argument("--emergency", action="store_true", default=False)
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Seconds to wait for the backup lock before giving up (0 = no wait)",
    )
