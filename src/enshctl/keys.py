"""Depot key acquisition — VDF fetch, parse, and depot.keys generation."""

import logging
import re
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from enshctl.download import InstallError
from enshctl.settings import APP_ID

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

VDF_SECTION_PATTERN = re.compile(r'"(\d+)"\s*\{[^}]*"DecryptionKey"\s+"([^"]+)"[^}]*\}')


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
        raise InstallError(msg) from e


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
        except InstallError as e:
            logger.warning("Failed to fetch from git repo: %s", e)
    try:
        vdf_content = fetch_key_vdf_from_archiveorg()
        keys = parse_key_vdf(vdf_content)
        if keys:
            generate_depot_keys(keys, output_path)
            return output_path
    except InstallError as e:
        logger.warning("Failed to fetch from archive.org: %s", e)
    msg = (
        "Failed to generate depot.keys from all sources. "
        "Provide DEPOT_KEYS_REPO with a valid git repository URL, "
        "or manually place a depot.keys file at /data/manifests/depot.keys, "
        "or use STEAM_PASSWORD for login-based download."
    )
    raise InstallError(msg)
