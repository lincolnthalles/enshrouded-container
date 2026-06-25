"""Enshrouded game server installation via DepotDownloader."""

import functools
import json
import logging
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from os import chown, environ
from typing import TYPE_CHECKING

from enshctl.backup import human_size
from enshctl.download import DownloadConfig, download_depots
from enshctl.settings import (
    APP_ID,
    DEPOT_DOWNLOADER,
    DEPOT_ID,
    LATEST_MANIFEST_FILE,
    MANIFEST_TMP_DIR,
    MANIFESTS_DIR,
    STATUS_FILE,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

DEPOT_KEY_PATTERN = re.compile(r"Got depot key for (\d+) result: OK")
MANIFEST_PATTERN = re.compile(r"Manifest\s+(\d+)\s+\((\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\)")
VDF_SECTION_PATTERN = re.compile(r'"(\d+)"\s*\{[^}]*"DecryptionKey"\s+"([^"]+)"[^}]*\}')


def get_version() -> str:
    return environ.get("VERSION", "latest").strip().lower()


def get_force_install() -> bool:
    return environ.get("FORCE_INSTALL", "").strip().lower() in ("1", "true", "yes")


def get_manifesthub_api_token() -> str | None:
    val = environ.get("MANIFESTHUB_API_TOKEN", "").strip()
    return val or None


def get_manifesthub_api_url() -> str | None:
    val = environ.get("MANIFESTHUB_API_URL", "").strip().rstrip("/")
    return val or None


def get_depot_keys_repo() -> str | None:
    val = environ.get("DEPOT_KEYS_REPO", "").strip()
    return val or None


DEFAULT_MIN_FREE_SPACE = 10 * 1024**3


def get_min_free_space() -> int:
    try:
        return int(environ.get("INSTALL_MIN_FREE_SPACE", str(DEFAULT_MIN_FREE_SPACE)))
    except ValueError, TypeError:
        return DEFAULT_MIN_FREE_SPACE


def fetch_manifests() -> list[dict[str, str]]:
    cmd = [
        *DEPOT_DOWNLOADER,
        "-app",
        APP_ID,
        "-depot",
        DEPOT_ID,
        "-dir",
        MANIFEST_TMP_DIR,
        "-manifest-only",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    output = result.stdout + result.stderr
    manifests: list[dict[str, str]] = []
    pattern = re.compile(r"Manifest\s+(\d+)\s+\((\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\)")
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            manifests.append(
                {
                    "manifest_id": m.group(1),
                    "timestamp": m.group(2),
                    "branch": "public",
                },
            )
    return manifests


def _write_latest_manifest(manifest_id: str, timestamp: str) -> None:
    """Persist the resolved latest manifest to a control file for offline fallback."""
    LATEST_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = f"{manifest_id}-{timestamp}"
    if LATEST_MANIFEST_FILE.exists() and LATEST_MANIFEST_FILE.read_text().strip() == content:
        return
    LATEST_MANIFEST_FILE.write_text(content)
    logger.info("Recorded latest manifest to %s", LATEST_MANIFEST_FILE)


def _read_latest_manifest() -> str | None:
    """Read the previously recorded latest manifest ID from the control file."""
    if not LATEST_MANIFEST_FILE.exists():
        return None
    content = LATEST_MANIFEST_FILE.read_text().strip()
    if not content:
        return None
    parts = content.split("-", 1)
    if len(parts) != 2 or not parts[0].isdigit():
        logger.warning("Malformed control file %s: %s", LATEST_MANIFEST_FILE, content)
        return None
    return parts[0]


def resolve_manifest(version_spec: str) -> str:
    """Resolve a VERSION value to a specific manifest ID."""
    if not version_spec or version_spec == "latest":
        manifests = fetch_manifests()
        if not manifests:
            cached = _read_latest_manifest()
            if cached is not None:
                logger.warning(
                    "fetch_manifests failed, falling back to cached manifest %s from %s",
                    cached,
                    LATEST_MANIFEST_FILE,
                )
                return cached
            logger.error("No manifests found from DepotDownloader and no cached manifest available")
            sys.exit(1)
        latest = max(manifests, key=lambda m: m["timestamp"])
        logger.info("Resolved 'latest' to manifest %s (%s)", latest["manifest_id"], latest["timestamp"])
        _write_latest_manifest(latest["manifest_id"], latest["timestamp"])
        return latest["manifest_id"]

    if version_spec.startswith("build:"):
        build_id = version_spec.removeprefix("build:")
        manifests = fetch_manifests()
        for m in manifests:
            if m.get("branch") == build_id or m.get("manifest_id", "").endswith(build_id):
                logger.info("Resolved build:%s to manifest %s", build_id, m["manifest_id"])
                return m["manifest_id"]
        logger.warning("Build %s not found in manifests, treating as manifest ID")
        return build_id

    if version_spec.isdigit():
        logger.info("Using explicit manifest ID: %s", version_spec)
        return version_spec

    logger.error("Unknown VERSION format: %s", version_spec)
    sys.exit(1)


@functools.lru_cache(maxsize=1)
def check_manifestfile_support() -> bool:
    """Check whether the installed DepotDownloader supports -manifestfile/-depotkeys flags."""
    cmd = [*DEPOT_DOWNLOADER, "-manifestfile", "/dev/null", "-depotkeys", "/dev/null"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    output = (result.stdout + result.stderr).lower()
    supported = "unknown" not in output and "unrecognized" not in output
    if not supported:
        logger.warning(
            "DepotDownloader does not support -manifestfile/-depotkeys flags. "
            "Auth-free downloads unavailable. Use the DepotDownloaderMod fork "
            "or provide STEAM_USERNAME/STEAM_PASSWORD."
        )
    return supported


def _infer_git_branch_and_path(repo_url: str) -> tuple[str, str]:
    stripped = repo_url.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/"):
        if stripped.startswith(prefix):
            path = stripped.removeprefix(prefix)
            parts = path.split("/")
            if len(parts) >= 4 and parts[2] == "tree":
                return parts[3], "/".join(parts[4:])
            return "main", ""
    return "main", ""


def _fetch_url(url: str, timeout: int = 30) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Dedicated Server Orchestrator"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        msg = f"Failed to fetch {url}: {e}"
        raise RuntimeError(msg) from e


def fetch_key_vdf_from_git(repo_url: str) -> str:
    branch, extra = _infer_git_branch_and_path(repo_url)
    base = "https://raw.githubusercontent.com"
    url = f"{base}/{repo_url.removeprefix('https://github.com/').removeprefix('http://github.com/').split('/tree/')[0].rstrip('/')}/{branch}"
    if extra:
        url = f"{url}/{extra}"
    key_path = f"{url}/{APP_ID}/key.vdf"
    logger.info("Fetching depot keys from git repo: %s", key_path)
    return _fetch_url(key_path)


def fetch_key_vdf_from_archiveorg() -> str:
    url = f"https://archive.org/download/manifest-hub-repo/NEW-depot-keys.zip/NEW-depot-keys/{APP_ID}/key.vdf"
    logger.info("Fetching depot keys from archive.org: %s", url)
    return _fetch_url(url)


def parse_key_vdf(content: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for match in VDF_SECTION_PATTERN.finditer(content):
        depot_id = match.group(1)
        hex_key = match.group(2)
        keys[depot_id] = hex_key
    return keys


def generate_depot_keys(depot_keys: dict[str, str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{depot_id};{hex_key}" for depot_id, hex_key in sorted(depot_keys.items())]
    content = "\n".join(lines) + "\n" if lines else "\n"
    output_path.write_text(content)
    logger.info("Generated depot.keys at %s (%d entries)", output_path, len(lines))


def ensure_depot_keys(manifests_dir: Path, repo_url: str | None) -> Path:
    output_path = manifests_dir / "depot.keys"
    if output_path.exists():
        logger.info("depot.keys already exists at %s", output_path)
        return output_path
    if repo_url:
        try:
            vdf_content = fetch_key_vdf_from_git(repo_url)
            keys = parse_key_vdf(vdf_content)
            if keys:
                generate_depot_keys(keys, output_path)
                return output_path
        except RuntimeError as e:
            logger.warning("Failed to fetch from git repo: %s", e)
    try:
        vdf_content = fetch_key_vdf_from_archiveorg()
        keys = parse_key_vdf(vdf_content)
        if keys:
            generate_depot_keys(keys, output_path)
            return output_path
    except RuntimeError as e:
        logger.warning("Failed to fetch from archive.org: %s", e)
    msg = (
        "Failed to generate depot.keys from all sources. "
        "Provide DEPOT_KEYS_REPO with a valid git repository URL, "
        "or manually place a depot.keys file at /data/manifests/depot.keys, "
        "or use STEAM_PASSWORD for login-based download."
    )
    raise RuntimeError(msg)


def download_manifest_from_hub(
    depot_id: str,
    manifest_id: str,
    output_dir: Path,
    api_key: str,
    api_url: str,
) -> Path:
    url = f"{api_url}/manifest?apikey={api_key}&depotid={depot_id}&manifestid={manifest_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{depot_id}_{manifest_id}.manifest"
    output_path = output_dir / filename
    logger.info("Downloading manifest %s from %s", manifest_id, api_url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Dedicated Server Orchestrator"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
            if "application/json" in content_type:
                error_data = json.loads(data)
                error_msg = error_data.get("error") or error_data.get("message") or str(error_data)
                hub_err = f"ManifestHub API error: {error_msg}"
                raise RuntimeError(hub_err)
            output_path.write_bytes(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        msg = f"ManifestHub API HTTP {e.code}: {body[:500]}"
        raise RuntimeError(msg) from e
    except urllib.error.URLError as e:
        msg2 = f"ManifestHub API request failed: {e}"
        raise RuntimeError(msg2) from e
    else:
        logger.info("Downloaded %s", filename)
        return output_path


def ensure_manifest_file(
    manifest_id: str,
    manifests_dir: Path,
    api_key: str | None,
    api_url: str,
) -> Path | None:
    filename = f"{DEPOT_ID}_{manifest_id}.manifest"
    manifest_path = manifests_dir / filename
    if manifest_path.exists():
        return manifest_path
    if not api_key:
        return None
    return download_manifest_from_hub(DEPOT_ID, manifest_id, manifests_dir, api_key, api_url)


def list_manifests_via_depotdownloader() -> list[str]:
    cmd = [
        *DEPOT_DOWNLOADER,
        "-app",
        APP_ID,
        "-depot",
        DEPOT_ID,
        "-dir",
        MANIFEST_TMP_DIR,
        "-manifest-only",
        "-os",
        "windows",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    output = result.stdout + result.stderr
    manifest_ids = [m.group(1) for m in MANIFEST_PATTERN.finditer(output)]
    if not manifest_ids:
        logger.warning("No manifests discovered from DepotDownloader")
    else:
        logger.info("Discovered %d manifest(s) via DepotDownloader", len(manifest_ids))
    return manifest_ids


def fetch_missing_manifests(
    manifest_ids: list[str],
    manifests_dir: Path,
    api_key: str,
    api_url: str,
) -> None:
    for mid in manifest_ids:
        filename = f"{DEPOT_ID}_{mid}.manifest"
        manifest_path = manifests_dir / filename
        if manifest_path.exists():
            continue
        try:
            download_manifest_from_hub(DEPOT_ID, mid, manifests_dir, api_key, api_url)
        except RuntimeError:
            logger.exception("Failed to fetch manifest %s", mid)


def prepare_manifests() -> None:
    depot_keys_repo = get_depot_keys_repo()
    manifest_api_token = get_manifesthub_api_token()
    manifest_api_url = get_manifesthub_api_url()

    if not manifest_api_token:
        logger.info("No MANIFESTHUB_API_TOKEN, skipping auth-free setup")
        return
    if manifest_api_token and not manifest_api_url:
        logger.error(
            "MANIFESTHUB_API_TOKEN is set but MANIFESTHUB_API_URL is not. "
            "Set MANIFESTHUB_API_URL to use manifest tokens."
        )
        sys.exit(1)
    has_manifest_support = check_manifestfile_support()
    if not has_manifest_support:
        logger.warning(
            "Auth-free manifest setup requested but DepotDownloader does not support "
            "-manifestfile/-depotkeys flags. Will fall back to Steam login if available."
        )
        return
    ensure_depot_keys(MANIFESTS_DIR, depot_keys_repo)
    if manifest_api_token and manifest_api_url:
        discovered = list_manifests_via_depotdownloader()
        if discovered:
            fetch_missing_manifests(discovered, MANIFESTS_DIR, manifest_api_token, manifest_api_url)


def _ensure_manifest_for_version(manifest_id: str) -> Path:
    """Ensure the .manifest file exists for the given version, fetching from ManifestHub if possible."""
    manifest_file = MANIFESTS_DIR / f"{DEPOT_ID}_{manifest_id}.manifest"
    manifest_api_token = get_manifesthub_api_token()
    api_url = get_manifesthub_api_url()
    has_manifest_support = check_manifestfile_support()
    if not manifest_file.exists() and manifest_api_token and not api_url:
        logger.error(
            "Manifest file missing for version %s and MANIFESTHUB_API_TOKEN is set "
            "but MANIFESTHUB_API_URL is not. Set MANIFESTHUB_API_URL to enable manifest downloads.",
            manifest_id,
        )
        sys.exit(1)
    if not manifest_file.exists() and api_url and manifest_api_token and has_manifest_support:
        logger.info(
            "Manifest file missing for version %s, fetching from ManifestHub",
            manifest_id,
        )
        try:
            download_manifest_from_hub(DEPOT_ID, manifest_id, MANIFESTS_DIR, manifest_api_token, api_url)
        except RuntimeError:
            logger.exception("Failed to fetch manifest for version %s from ManifestHub", manifest_id)
    return manifest_file


def download_version(
    manifest_id: str,
    *,
    force: bool = False,
    steam_username: str | None = None,
    steam_password: str | None = None,
) -> Path:
    """Download a specific manifest version via DepotDownloader.

    Args:
        manifest_id: The Steam manifest ID to download.
        force: If True, re-download even if already installed.
        steam_username: Optional Steam username for authenticated downloads.
        steam_password: Optional Steam password (paired with username).
    """
    target_dir = MANIFESTS_DIR / manifest_id
    status_file = target_dir / STATUS_FILE

    if not force and status_file.exists():
        logger.info("Version %s already installed (status file present) at %s", manifest_id, target_dir)
        return target_dir

    # Disk space check: account for partial downloads of the same manifest
    partial_size = 0
    if target_dir.exists():
        partial_size = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file() and not f.is_symlink())
    free = shutil.disk_usage(MANIFESTS_DIR).free
    effective_free = free + partial_size
    min_free = get_min_free_space()
    if effective_free < min_free:
        logger.error(
            "Insufficient disk space for install. Need %s, have %s effective (%s free + %s from partial download).",
            human_size(min_free),
            human_size(effective_free),
            human_size(free),
            human_size(partial_size),
        )
        sys.exit(1)

    target_dir.mkdir(parents=True, exist_ok=True)
    uid = int(environ.get("PUID", "1000"))
    gid = int(environ.get("PGID", "1000"))
    try:
        chown(MANIFESTS_DIR, uid, gid)
        chown(target_dir, uid, gid)
    except PermissionError:
        logger.info("Not running as root, skipping chown for %s", target_dir)

    manifest_file = _ensure_manifest_for_version(manifest_id)
    depot_keys_path = MANIFESTS_DIR / "depot.keys"
    has_manifest_support = check_manifestfile_support()
    use_auth_free = not steam_username and depot_keys_path.exists() and manifest_file.exists() and has_manifest_support

    if get_version() == "latest":
        config = DownloadConfig()
    elif use_auth_free:
        config = DownloadConfig(
            use_manifestfile=True,
            manifest_file=manifest_file,
            depot_keys_path=depot_keys_path,
        )
    elif steam_username:
        config = DownloadConfig(username=steam_username, password=steam_password)
    elif manifest_file.exists():
        logger.error(
            "Manifest file exists for version %s but no depot.keys found. "
            "Set DEPOT_KEYS_REPO or STEAM_PASSWORD to enable download.",
            manifest_id,
        )
        sys.exit(1)
    else:
        config = DownloadConfig(use_qr=True, print_qr_message=True)
    download_depots(manifest_id, target_dir, config)

    exe = target_dir / "enshrouded_server.exe"
    if not exe.exists():
        logger.error("Download completed but %s not found", exe)
        sys.exit(1)

    status_file.touch()
    logger.info("Downloaded version %s to %s", manifest_id, target_dir)

    # Mark manifest files read-only as defense-in-depth
    subprocess.run(["chmod", "-R", "a-w", str(target_dir)], check=False)
    return target_dir


def ensure_install(*, force: bool = False) -> Path:
    version_spec = get_version()
    manifest_id = resolve_manifest(version_spec)
    manifest_file = MANIFESTS_DIR / f"{DEPOT_ID}_{manifest_id}.manifest"
    has_token = get_manifesthub_api_token() is not None
    has_password = environ.get("STEAM_PASSWORD") is not None
    if not manifest_file.exists() and not has_password and not has_token:
        logger.info(
            "Version %s not installed and no .manifest file, password, or token available. "
            "Will attempt anonymous download (latest only).",
            manifest_id,
        )
    return download_version(manifest_id, force=force)
