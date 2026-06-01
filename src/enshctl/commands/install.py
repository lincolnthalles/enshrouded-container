"""Install subcommand."""

import logging

from enshctl import install

logger = logging.getLogger(__name__)


def run() -> None:
    """Run the install subcommand."""
    version_spec = install.get_version()
    force = install.get_force_install()
    logger.info("Installing game version: %s (force=%s)", version_spec, force)
    target = install.ensure_install(force=force)
    logger.info("Game installed at: %s", target)
