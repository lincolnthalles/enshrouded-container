"""Tests for ManifestHub manifest downloads."""

from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest
from enshctl.download.types import InstallError
from enshctl.files import write_bytes_atomic
from enshctl.hub import download_manifest_from_hub, fetch_missing_manifests
from enshctl.paths import DEPOT_ID

if TYPE_CHECKING:
    from pathlib import Path


class _Response:
    def __init__(self, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._data = data
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def test_download_manifest_writes_atomically(tmp_path: Path) -> None:
    # GIVEN a successful ManifestHub response
    with patch("urllib.request.urlopen", return_value=_Response(b"manifest")):
        # WHEN downloading
        path = download_manifest_from_hub(DEPOT_ID, "999", tmp_path, "key", "https://hub.example")

    # THEN the final file exists with the response bytes and no temp remains
    assert path == tmp_path / f"{DEPOT_ID}_999.manifest"
    assert path.read_bytes() == b"manifest"
    assert path.stat().st_mode & 0o777 == 0o644
    assert list(tmp_path.iterdir()) == [path]


def test_download_manifest_rejects_empty_body(tmp_path: Path) -> None:
    # GIVEN an empty response body
    with (
        patch("urllib.request.urlopen", return_value=_Response(b"")),
        pytest.raises(InstallError, match="empty Manifest"),
    ):
        # WHEN downloading
        download_manifest_from_hub(DEPOT_ID, "999", tmp_path, "key", "https://hub.example")


def test_download_manifest_rejects_invalid_ids(tmp_path: Path) -> None:
    # GIVEN a Manifest ID that would escape the manifests directory
    # WHEN downloading
    # THEN it fails before constructing the path
    with pytest.raises(InstallError, match="Invalid depot or Manifest ID"):
        download_manifest_from_hub(DEPOT_ID, "../escape", tmp_path, "key", "https://hub.example")


def test_write_bytes_atomic_replaces_existing(tmp_path: Path) -> None:
    # GIVEN an existing target
    target = tmp_path / "out.bin"
    target.write_bytes(b"old")

    # WHEN writing atomically
    write_bytes_atomic(target, b"new")

    # THEN the new bytes replace the old file with no temp left behind
    assert target.read_bytes() == b"new"
    assert list(tmp_path.iterdir()) == [target]


def test_write_bytes_atomic_cleans_temp_on_replace_failure(tmp_path: Path) -> None:
    # GIVEN a replacement that fails
    target = tmp_path / "out.bin"
    with (
        patch("pathlib.Path.replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        # WHEN writing atomically
        write_bytes_atomic(target, b"new")

    # THEN neither the target nor a temp file remains
    assert list(tmp_path.iterdir()) == []


def test_download_manifest_wraps_write_error(tmp_path: Path) -> None:
    # GIVEN a response whose atomic write fails
    with (
        patch("urllib.request.urlopen", return_value=_Response(b"manifest")),
        patch("enshctl.hub.write_bytes_atomic", side_effect=OSError("disk full")),
        pytest.raises(InstallError, match="disk full"),
    ):
        # WHEN downloading
        download_manifest_from_hub(DEPOT_ID, "999", tmp_path, "key", "https://hub.example")

    # THEN no Manifest or partial temp remains
    assert list(tmp_path.iterdir()) == []


def test_download_manifest_wraps_json_error(tmp_path: Path) -> None:
    # GIVEN a JSON response body that is not valid JSON
    with (
        patch("urllib.request.urlopen", return_value=_Response(b"not json", "application/json")),
        pytest.raises(InstallError, match="request failed"),
    ):
        # WHEN downloading
        download_manifest_from_hub(DEPOT_ID, "999", tmp_path, "key", "https://hub.example")


def test_download_manifest_wraps_non_object_json_error(tmp_path: Path) -> None:
    # GIVEN a JSON error body that is not an object
    with (
        patch("urllib.request.urlopen", return_value=_Response(b'["bad"]', "application/json")),
        pytest.raises(InstallError, match="ManifestHub API error"),
    ):
        # WHEN downloading
        download_manifest_from_hub(DEPOT_ID, "999", tmp_path, "key", "https://hub.example")


def test_fetch_missing_manifests_continues_after_error(tmp_path: Path) -> None:
    # GIVEN a downloader that fails for one Manifest and succeeds for the next
    calls: list[str] = []

    def _download(_depot_id: str, manifest_id: str, output_dir: Path, _key: str, _url: str) -> Path:
        calls.append(manifest_id)
        if manifest_id == "1":
            msg = "hub down"
            raise InstallError(msg)
        path = output_dir / f"{DEPOT_ID}_{manifest_id}.manifest"
        path.write_bytes(b"manifest")
        return path

    # WHEN prefetching both
    fetch_missing_manifests(["1", "2"], tmp_path, "key", "https://hub.example", download=_download)

    # THEN both are attempted and the successful Manifest is written
    assert calls == ["1", "2"]
    assert (tmp_path / f"{DEPOT_ID}_2.manifest").is_file()


def test_fetch_missing_manifests_skips_invalid_ids(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN an invalid traversal ID beside a numeric one
    calls: list[str] = []

    def _download(_depot_id: str, manifest_id: str, output_dir: Path, _key: str, _url: str) -> Path:
        calls.append(manifest_id)
        return output_dir / f"{DEPOT_ID}_{manifest_id}.manifest"

    # WHEN prefetching
    with caplog.at_level("WARNING", logger="enshctl.hub"):
        fetch_missing_manifests(["../escape", "2"], tmp_path, "key", "https://hub.example", download=_download)

    # THEN only the numeric ID is attempted and the invalid one is warned about
    assert calls == ["2"]
    assert any("Skipping invalid Manifest ID" in record.message for record in caplog.records)
