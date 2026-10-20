"""Manifest discovery — DepotDownloader manifest listing and VERSION resolution."""

import functools
import logging
import subprocess
from typing import TYPE_CHECKING

from enshctl.download import MANIFEST_PATTERN, InstallError
from enshctl.paths import APP_ID, DEPOT_DOWNLOADER, DEPOT_ID, LATEST_MANIFEST_FILE, MANIFEST_TMP_DIR

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


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


def fetch_manifests(
    *,
    depot_downloader: tuple[str, ...] = DEPOT_DOWNLOADER,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, str]]:
    cmd = [
        *depot_downloader,
        "-app",
        APP_ID,
        "-depot",
        DEPOT_ID,
        "-dir",
        MANIFEST_TMP_DIR,
        "-manifest-only",
    ]
    result = run(cmd, capture_output=True, text=True, timeout=120, check=True)
    output = result.stdout + result.stderr
    manifests: list[dict[str, str]] = []
    for line in output.splitlines():
        m = MANIFEST_PATTERN.search(line)
        if m:
            manifests.append(
                {
                    "manifest_id": m.group(1),
                    "timestamp": m.group(2),
                    "branch": "public",
                },
            )
    return manifests


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


def _write_latest_manifest(manifest_id: str, timestamp: str, control_file: Path = LATEST_MANIFEST_FILE) -> None:
    """Persist the resolved latest manifest to a control file for offline fallback."""
    control_file.parent.mkdir(parents=True, exist_ok=True)
    content = f"{manifest_id}-{timestamp}"
    if control_file.exists() and control_file.read_text().strip() == content:
        return
    control_file.write_text(content)
    logger.info("Recorded latest manifest to %s", control_file)


def _read_latest_manifest(control_file: Path = LATEST_MANIFEST_FILE) -> str | None:
    """Read the previously recorded latest manifest ID from the control file."""
    if not control_file.exists():
        return None
    content = control_file.read_text().strip()
    if not content:
        return None
    parts = content.split("-", 1)
    if len(parts) != 2 or not parts[0].isdigit():
        logger.warning("Malformed control file %s: %s", control_file, content)
        return None
    return parts[0]


def resolve_manifest(
    version_spec: str,
    *,
    control_file: Path = LATEST_MANIFEST_FILE,
    fetch: Callable[[], list[dict[str, str]]] = fetch_manifests,
) -> str:
    """Resolve a VERSION value to a specific manifest ID."""
    if not version_spec or version_spec == "latest":
        manifests = fetch()
        if not manifests:
            cached = _read_latest_manifest(control_file)
            if cached is not None:
                logger.warning(
                    "fetch_manifests failed, falling back to cached manifest %s from %s",
                    cached,
                    control_file,
                )
                return cached
            msg = "No manifests found from DepotDownloader and no cached manifest available"
            raise InstallError(msg)
        latest = max(manifests, key=lambda m: m["timestamp"])
        logger.info("Resolved 'latest' to manifest %s (%s)", latest["manifest_id"], latest["timestamp"])
        _write_latest_manifest(latest["manifest_id"], latest["timestamp"], control_file)
        return latest["manifest_id"]

    if version_spec.startswith("build:"):
        build_id = version_spec.removeprefix("build:")
        manifests = fetch()
        for m in manifests:
            if m.get("branch") == build_id or m.get("manifest_id", "").endswith(build_id):
                logger.info("Resolved build:%s to manifest %s", build_id, m["manifest_id"])
                return m["manifest_id"]
        logger.warning("Build %s not found in manifests, treating as manifest ID")
        return build_id

    if version_spec.isdigit():
        logger.info("Using explicit manifest ID: %s", version_spec)
        return version_spec

    msg = f"Unknown VERSION format: {version_spec}"
    raise InstallError(msg)
