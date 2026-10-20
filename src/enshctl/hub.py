"""ManifestHub client — manifest file downloads."""

import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from enshctl.download import InstallError
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
                raise InstallError(hub_err)
            output_path.write_bytes(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        msg = f"ManifestHub API HTTP {e.code}: {body[:500]}"
        raise InstallError(msg) from e
    except urllib.error.URLError as e:
        msg = f"ManifestHub API request failed: {e}"
        raise InstallError(msg) from e
    else:
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
    for mid in manifest_ids:
        filename = f"{DEPOT_ID}_{mid}.manifest"
        manifest_path = manifests_dir / filename
        if manifest_path.exists():
            continue
        try:
            download(DEPOT_ID, mid, manifests_dir, api_key, api_url)
        except InstallError:
            logger.exception("Failed to fetch manifest %s", mid)
