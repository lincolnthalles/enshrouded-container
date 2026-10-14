"""Download subcommand: download a specific manifest with optional Steam auth or ManifestHub token."""

import argparse
import logging
import sys
from dataclasses import replace

from enshctl import install
from enshctl.settings import load_settings, normalize_api_url

logger = logging.getLogger(__name__)


def run() -> None:
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

    settings = load_settings()
    settings = replace(
        settings,
        steam_username=args.steam_username or settings.steam_username,
        steam_password=args.steam_password or settings.steam_password,
        manifesthub_api_token=args.api_token or settings.manifesthub_api_token,
        manifesthub_api_url=normalize_api_url(args.api_url) or settings.manifesthub_api_url,
        depot_keys_repo=args.depot_keys_repo or settings.depot_keys_repo,
    )

    username = settings.steam_username
    password = settings.steam_password

    logger.info(
        "Downloading manifest %s (auth: %s, token: %s)",
        args.manifest_id,
        "yes" if username else "no",
        "yes" if settings.manifesthub_api_token else "no",
    )

    install.prepare_manifests(settings)
    target = install.download_version(
        args.manifest_id,
        settings,
        steam_username=username,
        steam_password=password,
    )
    logger.info("Manifest %s downloaded at: %s", args.manifest_id, target)
