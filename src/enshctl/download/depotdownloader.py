"""DepotDownloader adapter — argv construction, output parsing, and per-depot execution."""

import functools
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from enshctl.download.types import DownloadConfig, InstallError, ManifestRecord
from enshctl.paths import APP_ID, DEPOT_DOWNLOADER, DEPOT_ID, MANIFEST_TMP_DIR

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

_DEPOT_KEY_PATTERN = re.compile(r"Got depot key for (\d+) result: OK")
_MANIFEST_PATTERN = re.compile(r"Manifest[ \t]+(\d+)[ \t]+\((\d{2}/\d{2}/\d{4}[ \t]+\d{2}:\d{2}:\d{2})\)")
_WINDOWS_ARGS = ("-os", "windows")


@functools.cache
def _probe_manifestfile_support(
    binary: tuple[str, ...],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    cmd = [*binary]
    try:
        result = run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("DepotDownloader support probe timed out; presuming -manifestfile/-depotkeys support")
        return True
    output = (result.stdout + result.stderr).lower()
    supported = "manifestfile" in output and "depotkeys" in output
    if not supported:
        logger.warning(
            "DepotDownloader does not support -manifestfile/-depotkeys flags. "
            "Auth-free downloads unavailable. Use the DepotDownloaderMod fork "
            "or provide STEAM_USERNAME/STEAM_PASSWORD."
        )
    return supported


@dataclass(frozen=True)
class DepotDownloader:
    """Adapter for every DepotDownloader invocation and listing format.

    The binary and runner must be hashable because the support probe caches
    their pair.
    """

    binary: tuple[str, ...] = DEPOT_DOWNLOADER
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    def fetch_manifests(self) -> list[ManifestRecord]:
        """List Manifests for the target depot, failing fast on a process error."""
        return self._list_records(DEPOT_ID, check=True)

    def list_manifest_ids(self) -> list[str]:
        """List Manifest IDs for the target depot, tolerating failure."""
        manifest_ids = [record.manifest_id for record in self._list_records(DEPOT_ID, check=False)]
        if not manifest_ids:
            logger.warning("No manifests discovered from DepotDownloader")
        else:
            logger.info("Discovered %d manifest(s) via DepotDownloader", len(manifest_ids))
        return manifest_ids

    def discover_depots(self) -> list[tuple[str, str]]:
        """Discover all depot IDs and their current Manifest IDs for the app."""
        depot_ids = _DEPOT_KEY_PATTERN.findall(self._list_output(None, check=False))
        if not depot_ids:
            return []

        depot_manifests: list[tuple[str, str]] = []
        for depot_id in depot_ids:
            records = self._list_records(depot_id, check=False)
            depot_manifests.append((depot_id, records[0].manifest_id if records else ""))

        logger.info(
            "Discovered depots: %s",
            ", ".join(f"{depot_id} (manifest {manifest_id})" for depot_id, manifest_id in depot_manifests),
        )
        return depot_manifests

    def download_depots(
        self,
        manifest_id: str,
        target_dir: Path,
        config: DownloadConfig,
        depot_manifests: list[tuple[str, str]] | None = None,
    ) -> None:
        """Download game depots via DepotDownloader using the given strategy config."""
        if config.print_qr_message:
            print(
                "No Steam or ManifestHub credentials found. "
                "A QR code will be displayed — scan it with the Steam mobile app to authenticate.",
                flush=True,
            )

        depot_manifests = (
            with_manifest_override(self.discover_depots(), manifest_id) if depot_manifests is None else depot_manifests
        )

        strategy_label = (
            "QR login"
            if config.use_qr
            else ("auth-free" if config.use_manifestfile else ("Steam auth" if config.username else "anonymous"))
        )

        for depot_id, manifest_id_for_depot in depot_manifests:
            depot_cmd = self._download_command(depot_id, manifest_id_for_depot, target_dir, config)
            logger.info("Downloading depot %s (%s)…", depot_id, strategy_label)

            try:
                result = self.run(depot_cmd, check=False, timeout=config.timeout)
            except subprocess.TimeoutExpired as exc:
                msg = f"DepotDownloader timed out ({config.timeout}s) for depot {depot_id}"
                raise InstallError(msg) from exc
            if result.returncode != 0:
                msg = f"DepotDownloader exited with code {result.returncode} for depot {depot_id}"
                raise InstallError(msg)

    def supports_manifestfile(self) -> bool:
        """Whether the binary documents Manifest-file inputs in its usage text."""
        return _probe_manifestfile_support(self.binary, self.run)

    def _list_command(self, depot_id: str | None) -> list[str]:
        cmd = [*self.binary, "-app", APP_ID]
        if depot_id is not None:
            cmd.extend(["-depot", depot_id])
        cmd.extend([*_WINDOWS_ARGS, "-dir", MANIFEST_TMP_DIR, "-manifest-only"])
        return cmd

    def _list_output(self, depot_id: str | None, *, check: bool) -> str:
        result = self.run(
            self._list_command(depot_id),
            capture_output=True,
            text=True,
            timeout=120,
            check=check,
        )
        return result.stdout + result.stderr

    def _list_records(self, depot_id: str | None, *, check: bool) -> list[ManifestRecord]:
        output = self._list_output(depot_id, check=check)
        return [
            ManifestRecord(manifest_id=match.group(1), timestamp=match.group(2))
            for match in _MANIFEST_PATTERN.finditer(output)
        ]

    def _download_command(
        self,
        depot_id: str,
        manifest_id_for_depot: str,
        target_dir: Path,
        config: DownloadConfig,
    ) -> list[str]:
        cmd = [
            *self.binary,
            "-app",
            APP_ID,
            "-depot",
            depot_id,
            *_WINDOWS_ARGS,
            "-max-downloads",
            str(config.max_downloads),
            "-validate",
            "-verify-all",
            "-dir",
            str(target_dir),
        ]

        if manifest_id_for_depot:
            cmd.extend(["-manifest", manifest_id_for_depot])

        if config.use_manifestfile and config.depot_keys_path and config.manifest_file:
            cmd.extend(["-depotkeys", str(config.depot_keys_path)])
            cmd.extend(["-manifestfile", str(config.manifest_file)])

        if config.username:
            cmd.extend(["-username", config.username])
            if config.password:
                cmd.extend(["-password", config.password])
            cmd.append("-remember-password")

        if config.use_qr:
            cmd.append("-qr")

        return cmd


def with_manifest_override(
    depot_manifests: list[tuple[str, str]],
    manifest_id: str,
) -> list[tuple[str, str]]:
    """Override the target depot's manifest while leaving other depots at discovered IDs."""
    return [(depot, manifest_id if depot == DEPOT_ID else discovered_mid) for depot, discovered_mid in depot_manifests]
