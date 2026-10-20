"""Enshrouded game server installation via DepotDownloader — driver only."""

import logging
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from enshctl.download import (
    DownloadConfig,
    InstallError,
    _with_manifest_override,
    discover_depots,
    download_depots,
)
from enshctl.files import chown_tree, disk_free_bytes, read_tree_size
from enshctl.hub import download_manifest_from_hub, fetch_missing_manifests
from enshctl.keys import ensure_depot_keys
from enshctl.manifests import (
    check_manifestfile_support,
    list_manifests_via_depotdownloader,
    resolve_manifest,
)
from enshctl.settings import DEPOT_ID, MANIFESTS_DIR, STATUS_FILE
from enshctl.utils import human_size

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstallEnv:
    disk_free: Callable[[Path], int] = disk_free_bytes
    chown: Callable[..., None] = chown_tree
    chmod: Callable[..., object] = field(default_factory=lambda: subprocess.run)


@dataclass(frozen=True)
class DownloadAuth:
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class DownloadDeps:
    hub_download: Callable[[str, str, Path, str, str], Path] = download_manifest_from_hub
    support: Callable[[], bool] = check_manifestfile_support
    depot_download: Callable[[str, Path, DownloadConfig], None] = download_depots
    discover: Callable[[], list[tuple[str, str]]] | None = None


def _download_all_depots(
    manifest_id: str,
    target_dir: Path,
    config: DownloadConfig,
    *,
    discover: Callable[[], list[tuple[str, str]]] | None = None,
    depot_download: Callable[[str, Path, DownloadConfig], None] = download_depots,
) -> None:
    discover_fn = discover or discover_depots
    for _depot_id, depot_manifest_id in _with_manifest_override(discover_fn(), manifest_id):
        depot_download(depot_manifest_id or manifest_id, target_dir, config)


def prepare_manifests(
    settings: AppSettings,
    *,
    support: Callable[[], bool] = check_manifestfile_support,
    keys: Callable[[Path, str | None], Path] = ensure_depot_keys,
    list_manifests: Callable[[], list[str]] = list_manifests_via_depotdownloader,
    fetch_missing: Callable[[list[str], Path, str, str], None] = fetch_missing_manifests,
) -> None:
    depot_keys_repo = settings.depot_keys_repo
    manifest_api_token = settings.manifesthub_api_token
    manifest_api_url = settings.manifesthub_api_url

    if not manifest_api_token:
        logger.info("No MANIFESTHUB_API_TOKEN, skipping auth-free setup")
        return
    if manifest_api_token and not manifest_api_url:
        msg = (
            "MANIFESTHUB_API_TOKEN is set but MANIFESTHUB_API_URL is not. "
            "Set MANIFESTHUB_API_URL to use manifest tokens."
        )
        raise InstallError(msg)
    has_manifest_support = support()
    if not has_manifest_support:
        logger.warning(
            "Auth-free manifest setup requested but DepotDownloader does not support "
            "-manifestfile/-depotkeys flags. Will fall back to Steam login if available."
        )
        return
    keys(MANIFESTS_DIR, depot_keys_repo)
    if manifest_api_token and manifest_api_url:
        discovered = list_manifests()
        if discovered:
            fetch_missing(discovered, MANIFESTS_DIR, manifest_api_token, manifest_api_url)


def _ensure_manifest_for_version(
    manifest_id: str,
    settings: AppSettings,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
    support: Callable[[], bool] = check_manifestfile_support,
    hub_download: Callable[[str, str, Path, str, str], Path] = download_manifest_from_hub,
) -> Path:
    """Ensure the .manifest file exists for the given version, fetching from ManifestHub if possible."""
    manifest_file = manifests_dir / f"{DEPOT_ID}_{manifest_id}.manifest"
    manifest_api_token = settings.manifesthub_api_token
    api_url = settings.manifesthub_api_url
    has_manifest_support = support()
    if not manifest_file.exists() and manifest_api_token and not api_url:
        msg = (
            f"Manifest file missing for version {manifest_id} and MANIFESTHUB_API_TOKEN is set "
            "but MANIFESTHUB_API_URL is not. Set MANIFESTHUB_API_URL to enable manifest downloads."
        )
        raise InstallError(msg)
    if not manifest_file.exists() and api_url and manifest_api_token and has_manifest_support:
        logger.info(
            "Manifest file missing for version %s, fetching from ManifestHub",
            manifest_id,
        )
        try:
            hub_download(DEPOT_ID, manifest_id, manifests_dir, manifest_api_token, api_url)
        except InstallError:
            logger.exception("Failed to fetch manifest for version %s from ManifestHub", manifest_id)
    return manifest_file


def download_version(
    manifest_id: str,
    settings: AppSettings,
    *,
    auth: DownloadAuth | None = None,
    manifests_dir: Path = MANIFESTS_DIR,
    env: InstallEnv | None = None,
    download: DownloadDeps | None = None,
) -> Path:
    """Download a specific manifest version via DepotDownloader.

    Args:
        manifest_id: The Steam manifest ID to download.
        settings: Process-wide settings; supplies defaults for unset overrides.
    """
    fs = env or InstallEnv()
    deps = download or DownloadDeps()
    auth = auth or DownloadAuth()
    effective_username = auth.username if auth.username is not None else settings.steam_username
    effective_password = auth.password if auth.password is not None else settings.steam_password
    target_dir = manifests_dir / manifest_id
    status_file = target_dir / STATUS_FILE

    if not settings.force_install and status_file.exists():
        logger.info("Version %s already installed (status file present) at %s", manifest_id, target_dir)
        return target_dir

    # Disk space check: account for partial downloads of the same manifest
    partial_size = read_tree_size(target_dir)
    free = fs.disk_free(manifests_dir)
    effective_free = free + partial_size
    min_free = settings.min_free_space
    if effective_free < min_free:
        msg = (
            f"Insufficient disk space for install. Need {human_size(min_free)}, have {human_size(effective_free)} "
            f"effective ({human_size(free)} free + {human_size(partial_size)} from partial download)."
        )
        raise InstallError(msg)

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        fs.chown(manifests_dir, target_dir, uid=settings.puid, gid=settings.pgid)
    except PermissionError:
        logger.info("Not running as root, skipping chown for %s", target_dir)

    manifest_file = _ensure_manifest_for_version(
        manifest_id, settings, manifests_dir=manifests_dir, support=deps.support, hub_download=deps.hub_download
    )
    depot_keys_path = manifests_dir / "depot.keys"
    has_manifest_support = deps.support()
    use_auth_free = (
        not effective_username and depot_keys_path.exists() and manifest_file.exists() and has_manifest_support
    )

    if use_auth_free:
        strategy = "auth-free"
        config = DownloadConfig(
            use_manifestfile=True,
            manifest_file=manifest_file,
            depot_keys_path=depot_keys_path,
        )
    elif effective_username:
        strategy = "Steam auth"
        config = DownloadConfig(username=effective_username, password=effective_password)
    elif manifest_file.exists():
        msg = (
            f"Manifest file exists for version {manifest_id} but no depot.keys found. "
            "Set DEPOT_KEYS_REPO or STEAM_PASSWORD to enable download."
        )
        raise InstallError(msg)
    elif settings.version == "latest":
        strategy = "anonymous"
        config = DownloadConfig()
    else:
        strategy = "QR login"
        config = DownloadConfig(use_qr=True, print_qr_message=True)
    logger.info("Downloading manifest %s via %s", manifest_id, strategy)
    _download_all_depots(
        manifest_id, target_dir, config, discover=deps.discover, depot_download=deps.depot_download
    )

    exe = target_dir / "enshrouded_server.exe"
    if not exe.exists():
        msg = f"Download completed but {exe} not found"
        raise InstallError(msg)

    status_file.touch()
    logger.info("Downloaded version %s to %s", manifest_id, target_dir)

    # Mark manifest files read-only as defense-in-depth
    fs.chmod(["chmod", "-R", "a-w", str(target_dir)], check=False)
    return target_dir


def ensure_install(
    settings: AppSettings,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
    resolve: Callable[[str], str] = resolve_manifest,
) -> Path:
    version_spec = settings.version
    manifest_id = resolve(version_spec)
    manifest_file = manifests_dir / f"{DEPOT_ID}_{manifest_id}.manifest"
    has_token = settings.manifesthub_api_token is not None
    has_password = settings.steam_password is not None
    if not manifest_file.exists() and not has_password and not has_token:
        logger.info(
            "Version %s not installed and no .manifest file, password, or token available. "
            "Will attempt anonymous download (latest only).",
            manifest_id,
        )
    return download_version(manifest_id, settings)
