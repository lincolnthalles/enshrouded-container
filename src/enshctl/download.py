"""DepotDownloader download orchestration — shared depot-iteration loop."""

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from enshctl.settings import APP_ID, DEPOT_DOWNLOADER, DEPOT_ID, MANIFEST_TMP_DIR

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

DEPOT_KEY_PATTERN = re.compile(r"Got depot key for (\d+) result: OK")
MANIFEST_PATTERN = re.compile(r"Manifest\s+(\d+)\s+\((\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\)")


@dataclass(frozen=True)
class DownloadConfig:
    """Strategy-specific parameters for DepotDownloader invocation."""

    username: str | None = None
    password: str | None = None
    use_manifestfile: bool = False
    depot_keys_path: Path | None = None
    manifest_file: Path | None = None
    use_qr: bool = False
    print_qr_message: bool = False
    timeout: int = 3600
    max_downloads: int = 8


def discover_depots() -> list[tuple[str, str]]:
    """Discover all depot IDs and their current manifest IDs for the app.

    Returns a list of (depot_id, manifest_id) tuples.
    """
    cmd = [
        *DEPOT_DOWNLOADER,
        "-app",
        APP_ID,
        "-os",
        "windows",
        "-dir",
        MANIFEST_TMP_DIR,
        "-manifest-only",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    output = result.stdout + result.stderr
    depot_ids = DEPOT_KEY_PATTERN.findall(output)
    if not depot_ids:
        logger.warning("No depots discovered, falling back to default depot %s", DEPOT_ID)
        return [(DEPOT_ID, "")]

    depot_manifests: list[tuple[str, str]] = []
    for depot_id in depot_ids:
        depot_cmd = [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            depot_id,
            "-os",
            "windows",
            "-dir",
            MANIFEST_TMP_DIR,
            "-manifest-only",
        ]
        depot_result = subprocess.run(depot_cmd, capture_output=True, text=True, timeout=120, check=False)
        depot_output = depot_result.stdout + depot_result.stderr
        manifest_match = MANIFEST_PATTERN.search(depot_output)
        discovered_mid = manifest_match.group(1) if manifest_match else ""
        depot_manifests.append((depot_id, discovered_mid))

    logger.info(
        "Discovered depots: %s",
        ", ".join(f"{d} (manifest {m})" for d, m in depot_manifests),
    )
    return depot_manifests


def download_depots(
    manifest_id: str,
    target_dir: Path,
    config: DownloadConfig,
) -> None:
    """Download game depots via DepotDownloader using the given strategy config.

    Iterates all discovered depots and runs DepotDownloader for each with the
    flags specified by ``config``.
    """
    if config.print_qr_message:
        print(
            "No Steam or ManifestHub credentials found. "
            "A QR code will be displayed — scan it with the Steam mobile app to authenticate.",
            flush=True,
        )

    depot_manifests = discover_depots()
    depot_manifests = [
        (depot, manifest_id if depot == DEPOT_ID else discovered_mid) for depot, discovered_mid in depot_manifests
    ]

    strategy_label = (
        "QR login"
        if config.use_qr
        else ("auth-free" if config.use_manifestfile else ("Steam auth" if config.username else "anonymous"))
    )

    for depot_id, manifest_id_for_depot in depot_manifests:
        depot_cmd = [
            *DEPOT_DOWNLOADER,
            "-app",
            APP_ID,
            "-depot",
            depot_id,
            "-os",
            "windows",
            "-max-downloads",
            str(config.max_downloads),
            "-validate",
            "-verify-all",
            "-dir",
            str(target_dir),
        ]

        if manifest_id_for_depot:
            depot_cmd.extend(["-manifest", manifest_id_for_depot])

        if config.use_manifestfile and config.depot_keys_path and config.manifest_file:
            depot_cmd.extend(["-depotkeys", str(config.depot_keys_path)])
            depot_cmd.extend(["-manifestfile", str(config.manifest_file)])

        if config.username:
            depot_cmd.extend(["-username", config.username])
            if config.password:
                depot_cmd.extend(["-password", config.password])
            depot_cmd.append("-remember-password")

        if config.use_qr:
            depot_cmd.append("-qr")

        logger.info("Downloading depot %s (%s)...", depot_id, strategy_label)

        try:
            result = subprocess.run(depot_cmd, check=False, timeout=config.timeout)
        except subprocess.TimeoutExpired:
            logger.exception("DepotDownloader timed out (%ds) for depot %s", config.timeout, depot_id)
            sys.exit(1)
        else:
            if result.returncode != 0:
                logger.error("DepotDownloader exited with code %d for depot %s", result.returncode, depot_id)
                sys.exit(1)
