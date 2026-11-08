"""Install subcommand."""

import logging
from typing import TYPE_CHECKING

from enshctl import staging
from enshctl.commands.parser import CommandParser
from enshctl.download.types import InstallError
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None, argv: Sequence[str] = ()) -> int:
    """Run the install subcommand."""
    _ = CommandParser("Install subcommand").parse(argv)
    settings = settings or load_settings()
    logger.info("Installing game version: %s (force=%s)", settings.version, settings.force_install)
    try:
        target = staging.ensure_installed(settings)
    except InstallError:
        logger.exception("Install failed")
        return 1
    logger.info("Game installed at: %s", target)
    return 0
