"""Install subcommand."""

import logging
import sys

from enshctl import download as download_flow, install
from enshctl.download import InstallError
from enshctl.settings import AppSettings, load_settings

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None) -> None:
    """Run the install subcommand."""
    settings = settings or load_settings()
    logger.info("Installing game version: %s (force=%s)", settings.version, settings.force_install)
    try:
        download_flow.prepare_manifests(settings)
        target = install.ensure_install(settings)
    except InstallError:
        logger.exception("Install failed")
        sys.exit(1)
    logger.info("Game installed at: %s", target)
