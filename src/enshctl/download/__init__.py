"""Download flow — Manifest acquisition, strategy selection, and depot execution."""

from importlib import import_module
from typing import TYPE_CHECKING

from enshctl.download.types import DownloadConfig, InstallError, ManifestFile

if TYPE_CHECKING:
    from enshctl.download.flow import download_version, prepare_manifests, validate_manifest_id
    from enshctl.download.io import DownloadIO, HostIO

__all__ = [
    "DownloadConfig",
    "DownloadIO",
    "HostIO",
    "InstallError",
    "ManifestFile",
    "download_version",
    "prepare_manifests",
    "validate_manifest_id",
]

_LAZY_MODULES = {
    "DownloadIO": "enshctl.download.io",
    "HostIO": "enshctl.download.io",
    "download_version": "enshctl.download.flow",
    "prepare_manifests": "enshctl.download.flow",
    "validate_manifest_id": "enshctl.download.flow",
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_MODULES.get(name)
    if module_name is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(import_module(module_name), name)
