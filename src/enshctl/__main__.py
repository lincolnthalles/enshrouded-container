"""Enshrouded server container entrypoint (PID 1).

Thin CLI dispatcher. All lifecycle logic lives in enshctl.commands.*.
"""

import argparse
import logging
import subprocess
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, override

from enshctl.commands import COMMANDS
from enshctl.settings import load_settings, normalize_api_url

if TYPE_CHECKING:
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


class _GameServerFilter(logging.Filter):
    """Filter out game server log entries from the orchestrator file log."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "source", "") != "gameserver"


def main() -> None:
    """Run the main entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

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

    base = load_settings()
    settings: AppSettings = replace(
        base,
        log_tail=args.log_tail or base.log_tail,
        manifesthub_api_token=args.api_token or base.manifesthub_api_token,
        manifesthub_api_url=normalize_api_url(args.api_url) or base.manifesthub_api_url,
        depot_keys_repo=args.depot_keys_repo or base.depot_keys_repo,
    )
    if settings.orchestrator_log_file:
        log_file = settings.orchestrator_log_file
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
        log_level = getattr(logging, settings.orchestrator_log_level.strip().upper(), logging.WARNING)
        file_handler.setLevel(log_level)
        logging.getLogger().addHandler(file_handler)

    try:
        COMMANDS[args.command](settings)
    except OSError, RuntimeError, subprocess.SubprocessError, ValueError:
        logger.exception("Fatal error during %s", args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()
