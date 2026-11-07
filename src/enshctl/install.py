"""Install orchestration — resolve a Version spec and delegate to the Download flow."""

from typing import TYPE_CHECKING

from enshctl.download.flow import download_version
from enshctl.manifests import resolve_manifest
from enshctl.paths import MANIFESTS_DIR

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from enshctl.download.io import DownloadIO, HostIO
    from enshctl.settings import AppSettings


def ensure_install(
    settings: AppSettings,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
    resolve: Callable[[str], str] = resolve_manifest,
    host: HostIO | None = None,
    source: DownloadIO | None = None,
) -> Path:
    version_spec = settings.version
    manifest_id = resolve(version_spec)
    return download_version(
        manifest_id,
        settings,
        manifests_dir=manifests_dir,
        version_spec=version_spec,
        host=host,
        source=source,
    )


def ensure_manifest(
    manifest_id: str,
    settings: AppSettings,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
    host: HostIO | None = None,
    source: DownloadIO | None = None,
) -> Path:
    """Ensure one specific Manifest ID is installed without re-resolving the Version spec."""
    return download_version(
        manifest_id,
        settings,
        manifests_dir=manifests_dir,
        version_spec="latest",
        host=host,
        source=source,
    )
