"""Download subcommand: download a specific manifest with optional Steam auth or ManifestHub token."""

import argparse
import logging
import sys
from dataclasses import replace

from enshctl import download as download_flow
from enshctl.download import InstallError
from enshctl.settings import AppSettings, load_settings, normalize_api_url

logger = logging.getLogger(__name__)


def run(settings: AppSettings | None = None) -> None:
    """Run the download subcommand."""
    parser = argparse.ArgumentParser(description="Download a specific game manifest with optional authentication")
    parser.add_argument("manifest_id", help="Steam manifest ID to download")
    parser.add_argument("--steam-username", default=None, help="Steam username for authenticated downloads")
    parser.add_argument("--steam-password", default=None, help="Steam password (omit to be prompted interactively)")
    parser.add_argument("--api-token", default=None, help="ManifestHub API token for auth-free download")
    parser.add_argument(
        "--api-url",
        default=None,
        help="ManifestHub API base URL",
    )
    parser.add_argument(
        "--depot-keys-repo",
        default=None,
        help="Git repository URL for depot decryption keys",
    )
    args = parser.parse_args(sys.argv[2:])

    base = settings or load_settings()
    settings = replace(
        base,
        steam_username=args.steam_username or base.steam_username,
        steam_password=args.steam_password or base.steam_password,
        manifesthub_api_token=args.api_token or base.manifesthub_api_token,
        manifesthub_api_url=normalize_api_url(args.api_url) or base.manifesthub_api_url,
        depot_keys_repo=args.depot_keys_repo or base.depot_keys_repo,
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
        sys.exit(1)
    logger.info("Manifest %s downloaded at: %s", args.manifest_id, target)
