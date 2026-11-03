"""Strict argument parsing for one CLI subcommand."""

import argparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class CommandParser(argparse.ArgumentParser):
    """Argument parser that requires an explicit subcommand argv."""

    def __init__(self, description: str) -> None:
        super().__init__(description=description, allow_abbrev=False)

    def parse(self, argv: Sequence[str]) -> argparse.Namespace:
        return self.parse_args(argv)
