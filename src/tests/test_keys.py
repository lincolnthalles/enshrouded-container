"""Tests for depot key acquisition."""

import http.client
from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest
from enshctl.download import InstallError
from enshctl.keys import fetch_key_vdf_from_archiveorg, generate_depot_keys

if TYPE_CHECKING:
    from pathlib import Path


class _Response:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def test_fetch_key_vdf_wraps_decode_error() -> None:
    # GIVEN a response with invalid UTF-8
    with (
        patch("urllib.request.urlopen", return_value=_Response(b"\xff")),
        pytest.raises(InstallError, match="Failed to fetch"),
    ):
        # WHEN fetching the key VDF
        fetch_key_vdf_from_archiveorg()


def test_fetch_key_vdf_wraps_http_exception() -> None:
    # GIVEN a malformed HTTP response
    with (
        patch("urllib.request.urlopen", side_effect=http.client.BadStatusLine("")),
        pytest.raises(InstallError, match="Failed to fetch"),
    ):
        # WHEN fetching the key VDF
        fetch_key_vdf_from_archiveorg()


def test_generate_depot_keys_writes_readable_file(tmp_path: Path) -> None:
    # GIVEN parsed depot keys
    output = tmp_path / "depot.keys"

    # WHEN generating the file
    generate_depot_keys({"2278520": "deadbeef"}, output)

    # THEN the keys are readable and have the shared file mode
    assert output.read_text() == "2278520;deadbeef\n"
    assert output.stat().st_mode & 0o777 == 0o644


def test_generate_depot_keys_wraps_write_error(tmp_path: Path) -> None:
    # GIVEN an atomic write that fails
    output = tmp_path / "depot.keys"
    with (
        patch("enshctl.keys.write_bytes_atomic", side_effect=OSError("disk full")),
        pytest.raises(InstallError, match="disk full"),
    ):
        # WHEN generating depot keys
        generate_depot_keys({"2278520": "deadbeef"}, output)

    # THEN no partial file remains
    assert not output.exists()
