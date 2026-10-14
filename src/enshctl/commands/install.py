"""Install subcommand."""

import logging

from enshctl import install
from enshctl.settings import load_settings

logger = logging.getLogger(__name__)


def run() -> None:
    """Run the install subcommand."""
    settings = load_settings()
    logger.info("Installing game version: %s (force=%s)", settings.version, settings.force_install)
    target = install.ensure_install(settings)
    logger.info("Game installed at: %s", target)
