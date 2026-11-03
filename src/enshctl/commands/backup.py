"""Backup subcommand — CLI entrypoint for the backup child process."""

import logging

from enshctl.backup.run import BackupSeams, run_request
from enshctl.backup_protocol import BackupOutcome, BackupRequest, add_arguments
from enshctl.settings import AppSettings, load_settings

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None, *, seams: BackupSeams | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Backup subprocess")
    add_arguments(parser)
    args, _ = parser.parse_known_args()
    request = BackupRequest.from_argv(args)
    resolved = settings or load_settings()

    code = run_request(request, resolved, seams=seams or BackupSeams())
    if code == BackupOutcome.SUCCESS:
        logger.info("Backup completed successfully")
    elif code == BackupOutcome.LOCK_HELD:
        logger.info("Backup skipped: another backup in progress")
    else:
        logger.warning("Backup failed (exit code %d)", code)
    return int(code)
