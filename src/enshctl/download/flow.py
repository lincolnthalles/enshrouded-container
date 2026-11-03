"""Install download flow — Manifest acquisition, strategy selection, and depot execution."""

import logging
from typing import TYPE_CHECKING, cast

from enshctl.download.depotdownloader import with_manifest_override
from enshctl.download.io import DownloadIO, HostIO, SystemDownloadIO, SystemHostIO
from enshctl.download.types import DownloadConfig, InstallError, ManifestFile
from enshctl.keys import depot_keys_path
from enshctl.paths import DEPOT_ID, MANIFESTS_DIR, STATUS_FILE
from enshctl.utils import human_size

if TYPE_CHECKING:
    from pathlib import Path

    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)


def prepare_manifests(
    settings: AppSettings,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
    source: DownloadIO | None = None,
) -> None:
    download_io = source or SystemDownloadIO()
    depot_keys_repo = settings.depot_keys_repo
    manifest_api_token = settings.manifesthub_api_token
    manifest_api_url = settings.manifesthub_api_url

    if not manifest_api_token and not depot_keys_repo:
        logger.info("No MANIFESTHUB_API_TOKEN, skipping auth-free setup")
        return
    if manifest_api_token and not manifest_api_url:
        msg = (
            "MANIFESTHUB_API_TOKEN is set but MANIFESTHUB_API_URL is not. "
            "Set MANIFESTHUB_API_URL to use manifest tokens."
        )
        raise InstallError(msg)
    if not download_io.supports_manifestfile():
        logger.warning(
            "Auth-free manifest setup requested but DepotDownloader does not support "
            "-manifestfile/-depotkeys flags. Will fall back to Steam login if available."
        )
        return
    download_io.ensure_depot_keys(manifests_dir, depot_keys_repo)
    if manifest_api_token and manifest_api_url:
        discovered = download_io.list_manifest_ids()
        if discovered:
            download_io.fetch_missing_manifests(discovered, manifests_dir, manifest_api_token, manifest_api_url)
        else:
            logger.warning("No manifests discovered; skipping Manifest prefetch")


def validate_manifest_id(manifest_id: str) -> None:
    if not (manifest_id.isascii() and manifest_id.isdigit()):
        msg = f"Invalid Manifest ID: {manifest_id!r}"
        raise InstallError(msg)


def _ensure_manifest_for_version(
    manifest_id: str,
    settings: AppSettings,
    *,
    manifests_dir: Path,
    has_support: bool,
    host: HostIO,
    source: DownloadIO,
) -> ManifestFile:
    """Ensure the Manifest file exists, carrying any acquisition failure."""
    manifest_path = manifests_dir / f"{DEPOT_ID}_{manifest_id}.manifest"
    if host.is_file(manifest_path):
        return ManifestFile(manifest_path, is_present=True)

    api_token = settings.manifesthub_api_token
    api_url = settings.manifesthub_api_url
    if api_token and not api_url:
        msg = (
            f"Manifest file missing for version {manifest_id} and MANIFESTHUB_API_TOKEN is set "
            "but MANIFESTHUB_API_URL is not. Set MANIFESTHUB_API_URL to enable manifest downloads."
        )
        raise InstallError(msg)
    if not api_token or not api_url or not has_support:
        return ManifestFile(manifest_path, is_present=False)

    logger.info("Manifest file missing for version %s, fetching from ManifestHub", manifest_id)
    try:
        manifest_path = source.download_manifest(DEPOT_ID, manifest_id, manifests_dir, api_token, api_url)
    except InstallError as exc:
        logger.warning("Failed to fetch manifest for version %s from ManifestHub: %s", manifest_id, exc)
        return ManifestFile(manifest_path, is_present=False, error=exc)
    if not host.is_file(manifest_path):
        error = InstallError(f"ManifestHub did not produce {manifest_path.name}")
        logger.warning("Manifest fetch for version %s produced no file: %s", manifest_id, error)
        return ManifestFile(manifest_path, is_present=False, error=error)
    return ManifestFile(manifest_path, is_present=True)


def _select_strategy(
    manifest_id: str,
    manifest: ManifestFile,
    settings: AppSettings,
    keys_path: Path,
    *,
    has_support: bool,
    has_keys: bool,
    is_latest: bool,
) -> tuple[str, DownloadConfig]:
    username = settings.steam_username
    if not username and has_keys and manifest.is_present and has_support:
        return "auth-free", DownloadConfig(
            use_manifestfile=True,
            manifest_file=manifest.path,
            depot_keys_path=keys_path,
        )
    if username:
        return "Steam auth", DownloadConfig(username=username, password=settings.steam_password)
    if manifest.is_present:
        if has_keys:
            reason = (
                "DepotDownloader lacks -manifestfile support. "
                "Use the DepotDownloaderMod fork or provide STEAM_USERNAME/STEAM_PASSWORD."
            )
        else:
            reason = "no depot.keys found. Set DEPOT_KEYS_REPO or STEAM_USERNAME/STEAM_PASSWORD to enable download."
        msg = f"Manifest file exists for version {manifest_id} but {reason}"
        raise InstallError(msg)

    if is_latest:
        strategy = "anonymous"
        config = DownloadConfig()
    else:
        strategy = "QR login"
        config = DownloadConfig(use_qr=True, print_qr_message=True)
    if manifest.error is not None:
        logger.warning("Proceeding with %s after Manifest acquisition failed: %s", strategy, manifest.error)
    return strategy, config


def download_version(
    manifest_id: str,
    settings: AppSettings,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
    version_spec: str | None = None,
    host: HostIO | None = None,
    source: DownloadIO | None = None,
) -> Path:
    """Download a specific Manifest ID via DepotDownloader.

    The Version spec that selected the Manifest ID controls the anonymous
    fallback: an empty spec or ``latest`` allows it; an explicit spec does not.
    """
    validate_manifest_id(manifest_id)
    host_io = cast("HostIO", host or SystemHostIO())
    download_io = cast("DownloadIO", source or SystemDownloadIO())
    selected_version = version_spec if version_spec is not None else settings.version
    is_latest = not selected_version or selected_version == "latest"
    target_dir = manifests_dir / manifest_id
    status_file = target_dir / STATUS_FILE

    if host_io.is_symlink(target_dir):
        msg = f"Refusing symlinked Manifest install directory: {target_dir}"
        raise InstallError(msg)
    if not settings.force_install and host_io.is_file(status_file):
        logger.info("Version %s already installed (status file present) at %s", manifest_id, target_dir)
        return target_dir

    # Disk space check: account for partial downloads of the same manifest
    partial_size = host_io.space.tree_size(target_dir)
    verdict = host_io.space.check(manifests_dir, required_bytes=settings.min_free_space, existing_bytes=partial_size)
    if not verdict.is_sufficient:
        msg = (
            f"Insufficient disk space for install. Need {human_size(verdict.required_bytes)}, "
            f"have {human_size(verdict.available_bytes)} effective "
            f"({human_size(verdict.free_bytes)} free + {human_size(verdict.existing_bytes)} from partial download)."
        )
        raise InstallError(msg)

    try:
        host_io.mkdir(target_dir)
    except OSError as e:
        msg = f"Cannot create Manifest install directory {target_dir}: {e}"
        raise InstallError(msg) from e
    try:
        host_io.chown(target_dir, uid=settings.puid, gid=settings.pgid)
    except PermissionError:
        logger.info("Not running as root, skipping chown for %s", target_dir)
    except OSError as e:
        msg = f"Failed to set ownership on {target_dir}: {e}"
        raise InstallError(msg) from e

    has_support = download_io.supports_manifestfile()
    manifest = _ensure_manifest_for_version(
        manifest_id,
        settings,
        manifests_dir=manifests_dir,
        has_support=has_support,
        host=host_io,
        source=download_io,
    )
    keys_path = depot_keys_path(manifests_dir)
    has_keys = host_io.is_file(keys_path)
    strategy, config = _select_strategy(
        manifest_id,
        manifest,
        settings,
        keys_path,
        has_support=has_support,
        has_keys=has_keys,
        is_latest=is_latest,
    )
    logger.info("Downloading manifest %s via %s", manifest_id, strategy)
    discovered = download_io.discover_depots()
    if not discovered:
        logger.warning("No depots discovered, falling back to default depot %s", DEPOT_ID)
        discovered = [(DEPOT_ID, "")]
    pinned = with_manifest_override(discovered, manifest_id)
    download_io.download_depots(manifest_id, target_dir, config, pinned)

    exe = target_dir / "enshrouded_server.exe"
    if not host_io.is_file(exe):
        msg = f"Download completed but {exe} not found"
        raise InstallError(msg)
    try:
        host_io.touch(status_file)
    except OSError as e:
        msg = f"Cannot write install marker {status_file}: {e}"
        raise InstallError(msg) from e
    logger.info("Downloaded version %s to %s", manifest_id, target_dir)
    host_io.make_readonly(target_dir)
    return target_dir
