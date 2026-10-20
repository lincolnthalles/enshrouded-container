"""Backup subcommand — CLI entrypoint for backup subprocess."""

import logging
import sys

from enshctl.backup_protocol import BackupOutcome
from enshctl.backup_runner import main as runner_main
from enshctl.settings import AppSettings  # noqa: TC001 — runtime annotation for registry test

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None) -> None:
    code = runner_main(settings)
    if code == BackupOutcome.SUCCESS:
        logger.info("Backup completed successfully")
    elif code == BackupOutcome.LOCK_HELD:
        logger.info("Backup skipped: another backup in progress")
    else:
        logger.warning("Backup failed (exit code %d)", code)
    sys.exit(code)
