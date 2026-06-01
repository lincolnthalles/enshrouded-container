"""Download subcommand: download a specific manifest with optional Steam auth or ManifestHub token."""

import argparse
import logging
import sys
from os import environ

from enshctl import install

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

    username = args.steam_username or environ.get("STEAM_USERNAME")
    password = args.steam_password or environ.get("STEAM_PASSWORD")

    if args.api_token:
        environ.setdefault("MANIFESTHUB_API_TOKEN", args.api_token)
    if args.api_url:
        environ.setdefault("MANIFESTHUB_API_URL", args.api_url)
    if args.depot_keys_repo:
        environ.setdefault("DEPOT_KEYS_REPO", args.depot_keys_repo)

    logger.info(
        "Downloading manifest %s (auth: %s, token: %s)",
        args.manifest_id,
        "yes" if username else "no",
        "yes" if args.api_token or environ.get("MANIFESTHUB_API_TOKEN") else "no",
    )

    install.prepare_manifests()
    target = install.download_version(
        args.manifest_id,
        steam_username=username,
        steam_password=password,
    )
    logger.info("Manifest %s downloaded at: %s", args.manifest_id, target)
