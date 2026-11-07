"""Version resolution — resolve a Version spec to a Manifest ID via DepotDownloader."""

import logging
from subprocess import SubprocessError
from typing import TYPE_CHECKING

from enshctl.download.depotdownloader import DepotDownloader
from enshctl.download.types import InstallError, ManifestRecord
from enshctl.paths import LATEST_MANIFEST_FILE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


def manifest_sort_key(manifest: ManifestRecord) -> tuple[int, int, int, int, int, int]:
    """Parse a DepotDownloader manifest timestamp for chronological comparison.

    DepotDownloader prints ``MM/DD/YYYY HH:MM:SS``; lexicographic comparison
    misorders across months, so parse to a component tuple instead.
    """
    try:
        date_part, time_part = manifest.timestamp.split(maxsplit=1)
        month, day, year = (int(part) for part in date_part.split("/"))
        hour, minute, second = (int(part) for part in time_part.split(":"))
    except ValueError:
        return (0, 0, 0, 0, 0, 0)
    return (year, month, day, hour, minute, second)


def record_latest_manifest(manifest_id: str, timestamp: str, control_file: Path = LATEST_MANIFEST_FILE) -> None:
    """Persist the resolved latest manifest to a control file for offline fallback."""
    control_file.parent.mkdir(parents=True, exist_ok=True)
    content = f"{manifest_id}-{timestamp}"
    if control_file.exists() and control_file.read_text().strip() == content:
        return
    control_file.write_text(content)
    logger.info("Recorded latest manifest to %s", control_file)


def cached_latest_manifest(control_file: Path = LATEST_MANIFEST_FILE) -> ManifestRecord | None:
    """Read the cached latest manifest ID and timestamp, if the control file is valid."""
    if not control_file.exists():
        return None
    content = control_file.read_text().strip()
    if not content:
        return None
    parts = content.split("-", 1)
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
        logger.warning("Malformed control file %s: %s", control_file, content)
        return None
    return ManifestRecord(manifest_id=parts[0], timestamp=parts[1])


def latest_manifest(fetch: Callable[[], list[ManifestRecord]] | None = None) -> ManifestRecord | None:
    """Return the newest listed Manifest without installing or caching it."""
    fetcher = fetch if fetch is not None else DepotDownloader().fetch_manifests
    manifests = fetcher()
    if not manifests:
        return None
    return max(manifests, key=manifest_sort_key)


def resolve_manifest(
    version_spec: str,
    *,
    control_file: Path = LATEST_MANIFEST_FILE,
    fetch: Callable[[], list[ManifestRecord]] | None = None,
) -> str:
    """Resolve a VERSION value to a specific manifest ID."""
    fetcher = fetch if fetch is not None else DepotDownloader().fetch_manifests
    if not version_spec or version_spec == "latest":
        fetch_error: SubprocessError | None = None
        try:
            latest = latest_manifest(fetcher)
        except SubprocessError as exc:
            logger.warning("Manifest listing failed (%s); trying cached manifest", exc)
            latest = None
            fetch_error = exc
        if latest is None:
            cached = cached_latest_manifest(control_file)
            if cached is not None:
                logger.warning(
                    "Falling back to cached manifest %s from %s",
                    cached.manifest_id,
                    control_file,
                )
                return cached.manifest_id
            if fetch_error is not None:
                msg = f"Manifest listing failed and no cached manifest available: {fetch_error}"
                raise InstallError(msg) from fetch_error
            msg = "No manifests found from DepotDownloader and no cached manifest available"
            raise InstallError(msg)
        logger.info("Resolved 'latest' to manifest %s (%s)", latest.manifest_id, latest.timestamp)
        record_latest_manifest(latest.manifest_id, latest.timestamp, control_file)
        return latest.manifest_id

    if version_spec.startswith("build:"):
        build_id = version_spec.removeprefix("build:")
        if not build_id:
            msg = "Build ID is empty"
            raise InstallError(msg)
        try:
            manifests = fetcher()
        except SubprocessError as exc:
            msg = f"Manifest listing failed while resolving build {build_id}: {exc}"
            raise InstallError(msg) from exc
        for m in manifests:
            if m.branch == build_id or m.manifest_id.endswith(build_id):
                logger.info("Resolved build:%s to manifest %s", build_id, m.manifest_id)
                return m.manifest_id
        if not (build_id.isascii() and build_id.isdigit()):
            msg = f"Build {build_id} not found in manifests and is not a numeric Manifest ID"
            raise InstallError(msg)
        logger.warning("Build %s not found in manifests, treating as manifest ID", build_id)
        return build_id

    if version_spec.isdigit():
        logger.info("Using explicit manifest ID: %s", version_spec)
        return version_spec

    msg = f"Unknown VERSION format: {version_spec}"
    raise InstallError(msg)
