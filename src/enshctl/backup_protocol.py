"""Backup parent/child protocol — outcome enum and typed request shared across the seam."""

import argparse
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path

from enshctl.backup.category import Category


class BackupOutcome(IntEnum):
    SUCCESS = 0
    LOCK_HELD = 1
    ERROR = 2


class Trigger(StrEnum):
    """Event that caused a Backup, orthogonal to its storage Category."""

    SCHEDULED = "scheduled"
    SHUTDOWN = "shutdown"
    UPDATE = "update"
    CRASH = "crash"
    MANUAL = "manual"


_TRIGGER_CATEGORIES = {
    Trigger.SCHEDULED: Category.LIVE,
    Trigger.SHUTDOWN: Category.COLD,
    Trigger.UPDATE: Category.COLD,
    Trigger.CRASH: Category.EMERGENCY,
}


@dataclass(frozen=True)
class BackupRequest:
    category: Category = Category.LIVE
    wait_seconds: int = 0
    detach: bool = False
    fmt: str | None = None
    level: int | None = None
    saves_dir: Path | None = None

    def __post_init__(self) -> None:
        """Coerce a raw Category string into the enum."""
        object.__setattr__(self, "category", Category(self.category))

    @classmethod
    def for_trigger(cls, trigger: Trigger, *, wait_seconds: int = 0) -> BackupRequest:
        """Build the request for a lifecycle trigger; manual callers pass a Category."""
        if trigger is Trigger.MANUAL:
            msg = "Manual backups select a Category explicitly"
            raise ValueError(msg)
        category = _TRIGGER_CATEGORIES[trigger]
        return cls(
            category=category,
            wait_seconds=wait_seconds,
            detach=trigger in (Trigger.SHUTDOWN, Trigger.UPDATE, Trigger.CRASH),
        )

    def to_argv(self) -> list[str]:
        argv: list[str] = []
        if self.category == Category.COLD:
            argv.append("--cold")
        elif self.category == Category.EMERGENCY:
            argv.append("--emergency")
        if self.wait_seconds > 0:
            argv.extend(["--wait", str(self.wait_seconds)])
        if self.fmt is not None:
            argv.extend(["--format", self.fmt])
        if self.level is not None:
            argv.extend(["--level", str(self.level)])
        if self.saves_dir is not None:
            argv.extend(["--saves-dir", str(self.saves_dir)])
        return argv

    @classmethod
    def from_argv(cls, args: argparse.Namespace) -> BackupRequest:
        category = Category.LIVE
        if args.cold:
            category = Category.COLD
        elif args.emergency:
            category = Category.EMERGENCY
        return cls(
            category=category,
            wait_seconds=args.wait,
            fmt=args.format,
            level=args.level,
            saves_dir=args.saves_dir,
        )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", default=None, type=str.lower, choices=["zstd", "gzip", "zip"])
    parser.add_argument("--level", type=int, default=None)
    # Parent-to-child propagation only; this is not an operator-facing option.
    parser.add_argument("--saves-dir", default=None, type=Path, help=argparse.SUPPRESS)
    category = parser.add_mutually_exclusive_group()
    category.add_argument("--cold", action="store_true", default=False)
    category.add_argument("--emergency", action="store_true", default=False)
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Seconds to wait for the backup lock before giving up (0 = no wait)",
    )
