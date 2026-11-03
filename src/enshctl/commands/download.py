"""Download subcommand: download a specific manifest with optional Steam auth or ManifestHub token."""

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from enshctl.commands.parser import CommandParser
from enshctl.download import flow as download_flow
from enshctl.download.types import InstallError
from enshctl.settings import AppSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None, argv: Sequence[str] = ()) -> int:
    """Run the download subcommand."""
    parser = CommandParser("Download a specific game manifest with optional authentication")
    parser.add_argument("manifest_id", help="Steam manifest ID to download")
    parser.add_argument("--steam-username", default=None, help="Steam username for authenticated downloads")
    parser.add_argument("--steam-password", default=None, help="Steam password (omit to be prompted interactively)")
    args = parser.parse(argv)

    base = settings or load_settings()
    settings = replace(
        base,
        steam_username=args.steam_username or base.steam_username,
        steam_password=args.steam_password or base.steam_password,
    )

    logger.info(
        "Downloading manifest %s (auth: %s, token: %s)",
        args.manifest_id,
        "yes" if settings.steam_username else "no",
        "yes" if settings.manifesthub_api_token else "no",
    )

    try:
        download_flow.validate_manifest_id(args.manifest_id)
        download_flow.prepare_manifests(settings)
        target = download_flow.download_version(args.manifest_id, settings, version_spec=args.manifest_id)
    except InstallError:
        logger.exception("Download failed")
        return 1
    logger.info("Manifest %s downloaded at: %s", args.manifest_id, target)
    return 0
