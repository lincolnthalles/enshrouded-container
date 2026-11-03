"""Debug-config subcommand — prints the generated config from env vars."""

import json
import sys
from typing import TYPE_CHECKING

from enshctl.commands.parser import CommandParser
from enshctl.config import env_to_dict, generate_config
from enshctl.settings import AppSettings  # noqa: TC001 — runtime annotation for registry test

if TYPE_CHECKING:
    from collections.abc import Sequence


def run(settings: AppSettings | None = None, argv: Sequence[str] = ()) -> int:
    """Run the debug-config subcommand."""
    _ = settings
    _ = CommandParser("Debug-config subcommand").parse(argv)
    print("=== env_to_dict() ===")
    env_overrides = env_to_dict()
    print(json.dumps(env_overrides, indent=2))
    print()

    print("=== generate_config() ===")
    config = generate_config()
    print(json.dumps(config, indent=2))
    print()

    print("Preview only — nothing written to /data/config/enshrouded_server.json", file=sys.stderr)
    return 0
