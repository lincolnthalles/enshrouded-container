"""Debug-config subcommand — prints the generated config from env vars."""

import json
import sys

from enshctl.config import env_to_dict, generate_config


def run() -> None:
    """Run the debug-config subcommand."""
    print("=== env_to_dict() ===")
    env_overrides = env_to_dict()
    print(json.dumps(env_overrides, indent=2))
    print()

    print("=== generate_config() ===")
    config = generate_config()
    print(json.dumps(config, indent=2))
    print()

    print("Written to: /data/config/enshrouded_server.json", file=sys.stderr)
