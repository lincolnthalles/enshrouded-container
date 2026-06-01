"""Enshrouded server container entrypoint (PID 1).

Thin CLI dispatcher. All lifecycle logic lives in enshctl.commands.*.
"""

import argparse
import logging
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from os import environ
from pathlib import Path

from enshctl.commands import COMMANDS

logger = logging.getLogger(__name__)


class _GameServerFilter(logging.Filter):
    """Filter out game server log entries from the orchestrator file log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "source", "") != "gameserver"


def main() -> None:
    """Run the main entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

    # Optional orchestrator file logging
    log_file = environ.get("ORCHESTRATOR_LOG_FILE", "").strip()
    if log_file:
        if log_file.lower() == "true":
            log_file = "/data/logs/orchestrator.log"
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=1,
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        file_handler.addFilter(_GameServerFilter())
        log_level_name = environ.get("ORCHESTRATOR_LOG_LEVEL", "WARNING").strip().upper()
        log_level = getattr(logging, log_level_name, logging.WARNING)
        file_handler.setLevel(log_level)
        logging.getLogger().addHandler(file_handler)

    parser = argparse.ArgumentParser(description="Enshrouded server container entrypoint")
    parser.add_argument(
        "command",
        nargs="?",
        default="start",
        choices=list(COMMANDS.keys()),
        help="Subcommand to execute (default: start)",
    )
    parser.add_argument(
        "--log-tail",
        action="store_true",
        default=False,
        help="Also tail the game's log file to stdout (env: LOG_TAIL)",
    )
    parser.add_argument(
        "--api-token",
        default=None,
        help="ManifestHub API token for fetching historical manifests (env: MANIFESTHUB_API_TOKEN)",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="ManifestHub API base URL (env: MANIFESTHUB_API_URL)",
    )
    parser.add_argument(
        "--depot-keys-repo",
        default=None,
        help="Git repository URL for depot decryption keys (env: DEPOT_KEYS_REPO)",
    )
    args = parser.parse_known_args()[0]

    if args.log_tail:
        environ.setdefault("LOG_TAIL", "true")
    if args.api_token:
        environ.setdefault("MANIFESTHUB_API_TOKEN", args.api_token)
    if args.api_url:
        environ.setdefault("MANIFESTHUB_API_URL", args.api_url)
    if args.depot_keys_repo:
        environ.setdefault("DEPOT_KEYS_REPO", args.depot_keys_repo)

    try:
        COMMANDS[args.command]()
    except OSError, RuntimeError, subprocess.SubprocessError, ValueError:
        logger.exception("Fatal error during %s", args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()
