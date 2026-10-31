"""ManifestHub client — manifest file downloads."""

import http.client
import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from enshctl.download.types import InstallError
from enshctl.files import write_bytes_atomic
from enshctl.paths import DEPOT_ID

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


def download_manifest_from_hub(
    depot_id: str,
    manifest_id: str,
    output_dir: Path,
    api_key: str,
    api_url: str,
) -> Path:
    if not (depot_id.isascii() and depot_id.isdigit() and manifest_id.isascii() and manifest_id.isdigit()):
        msg = f"Invalid depot or Manifest ID: {depot_id!r}, {manifest_id!r}"
        raise InstallError(msg)
    url = f"{api_url}/manifest?apikey={api_key}&depotid={depot_id}&manifestid={manifest_id}"
    filename = f"{depot_id}_{manifest_id}.manifest"
    output_path = output_dir / filename
    logger.info("Downloading manifest %s from %s", manifest_id, api_url)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        msg = f"Failed to create Manifest directory {output_dir}: {e}"
        raise InstallError(msg) from e

    data = b""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Dedicated Server Orchestrator"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
            if "application/json" in content_type:
                error_data = json.loads(data)
                if isinstance(error_data, dict):
                    error_msg = error_data.get("error") or error_data.get("message") or str(error_data)
                else:
                    error_msg = str(error_data)
                hub_err = f"ManifestHub API error: {error_msg}"
                raise InstallError(hub_err)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        msg = f"ManifestHub API HTTP {e.code}: {body[:500]}"
        raise InstallError(msg) from e
    except urllib.error.URLError as e:
        msg = f"ManifestHub API request failed: {e}"
        raise InstallError(msg) from e
    except (OSError, ValueError, http.client.HTTPException) as e:
        msg = f"ManifestHub API request failed: {e}"
        raise InstallError(msg) from e

    if not data:
        msg = "ManifestHub returned an empty Manifest"
        raise InstallError(msg)
    try:
        write_bytes_atomic(output_path, data)
    except OSError as e:
        msg = f"Failed to write manifest {output_path}: {e}"
        raise InstallError(msg) from e
    logger.info("Downloaded %s", filename)
    return output_path


def fetch_missing_manifests(
    manifest_ids: list[str],
    manifests_dir: Path,
    api_key: str,
    api_url: str,
    *,
    download: Callable[[str, str, Path, str, str], Path] = download_manifest_from_hub,
) -> None:
    for manifest_id in manifest_ids:
        if not (manifest_id.isascii() and manifest_id.isdigit()):
            logger.warning("Skipping invalid Manifest ID: %r", manifest_id)
            continue
        filename = f"{DEPOT_ID}_{manifest_id}.manifest"
        manifest_path = manifests_dir / filename
        if manifest_path.is_file():
            continue
        try:
            download(DEPOT_ID, manifest_id, manifests_dir, api_key, api_url)
        except InstallError:
            logger.exception("Failed to fetch manifest %s", manifest_id)
