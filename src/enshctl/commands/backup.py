"""Backup subcommand — CLI entrypoint for the backup child process."""

import logging
from typing import TYPE_CHECKING

from enshctl.backup.run import BackupSeams, run_request
from enshctl.backup_protocol import BackupOutcome, BackupRequest, add_arguments
from enshctl.commands.parser import CommandParser
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def run(
    settings: AppSettings | None = None,
    argv: Sequence[str] = (),
    *,
    seams: BackupSeams | None = None,
) -> int:
    parser = CommandParser("Backup subprocess")
    add_arguments(parser)
    args = parser.parse(argv)
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
