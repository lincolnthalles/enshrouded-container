"""Backup subcommand — CLI entrypoint for backup subprocess."""

import logging
import sys

from enshctl.backup_runner import EXIT_LOCK_HELD, EXIT_SUCCESS, main as runner_main

logger = logging.getLogger(__name__)


def run() -> None:
    code = runner_main()
    if code == EXIT_SUCCESS:
        logger.info("Backup completed successfully")
    elif code == EXIT_LOCK_HELD:
        logger.info("Backup skipped: another backup in progress")
    else:
        logger.warning("Backup failed (exit code %d)", code)
    sys.exit(code)
