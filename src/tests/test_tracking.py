"""Tests for stale env key tracking."""

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from enshctl.config import generate_config, write_generated_config
from enshctl.settings import AppSettings
from enshctl.tracking import read_tracked_paths, write_tracked_paths

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _settings() -> AppSettings:
    return AppSettings(backup_dir="/data/backups")


def _generate(
    base: dict[str, Any],
    source: dict[str, str],
    tracking_file: Path,
    *,
    is_persisted: bool = True,
) -> dict[str, Any]:
    from unittest.mock import patch

    with patch("enshctl.config.load_base_config", return_value=deepcopy(base)):
        return generate_config(source, tracking_file=tracking_file, is_persisted=is_persisted)


def test_removed_env_var_removes_setting(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN a persisted base and tracking file recording a nested factor
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("gameSettings", "resourceDropStackAmountFactor")}))
    base = {"gameSettings": {"resourceDropStackAmountFactor": 2.0, "playerHealthFactor": 1.5}}

    # WHEN generating without the variable
    with caplog.at_level("WARNING", logger="enshctl.config"):
        result = _generate(base, {}, tracking_file)

    # THEN the stale factor is absent, its sibling survives, and a warning names it
    assert result["gameSettings"] == {"playerHealthFactor": 1.5}
    assert "resourceDropStackAmountFactor" in caplog.text


def test_future_key_is_removed(tmp_path: Path) -> None:
    # GIVEN a tracked key the current game schema does not define
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("futureGameKey",)}))
    base = {"futureGameKey": "value", "name": "Server"}

    # WHEN generating without the variable
    result = _generate(base, {}, tracking_file)

    # THEN the future key is absent and other keys survive
    assert "futureGameKey" not in result
    assert result["name"] == "Server"


def test_untracked_keys_survive_removal(tmp_path: Path) -> None:
    # GIVEN a base holding a never-tracked manual key and a stale tracked key
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("slotCount",)}))
    base: dict[str, Any] = {"slotCount": 8, "name": "Manual", "gameSettings": {"bans": []}}

    # WHEN generating without the tracked variable
    result = _generate(base, {}, tracking_file)

    # THEN the stale key is gone and untracked keys are retained
    assert "slotCount" not in result
    assert result["name"] == "Manual"
    assert result["gameSettings"] == {"bans": []}


def test_tracked_key_loses_after_file_edit(tmp_path: Path) -> None:
    # GIVEN a tracked key edited directly in the persisted config
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("slotCount",)}))
    base = {"slotCount": 99}

    # WHEN generating without the variable
    result = _generate(base, {}, tracking_file)

    # THEN the edited value does not survive
    assert "slotCount" not in result


def test_sibling_keys_survive_nested_removal(tmp_path: Path) -> None:
    # GIVEN one stale key and sibling keys under the same settings object
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("gameSettings", "playerHealthFactor")}))
    base = {"gameSettings": {"playerHealthFactor": 2.0, "isPvp": True}}

    # WHEN generating without the stale variable
    result = _generate(base, {}, tracking_file)

    # THEN the sibling key survives
    assert result["gameSettings"] == {"isPvp": True}


def test_composite_object_removes_only_its_keys(tmp_path: Path) -> None:
    # GIVEN a JSON object value tracked per individual key plus another base key
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(
        tracking_file,
        frozenset({("gameSettings", "a"), ("gameSettings", "b")}),
    )
    base = {"gameSettings": {"a": 1, "b": 2, "other": 3}}

    # WHEN generating without the object variable
    result = _generate(base, {}, tracking_file)

    # THEN only the object keys are gone and the other key survives
    assert result["gameSettings"] == {"other": 3}


def test_array_value_removes_wholly(tmp_path: Path) -> None:
    # GIVEN a tracked array key holding multiple values
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("tags",)}))
    base = {"tags": ["English", "Exploration"], "name": "Server"}

    # WHEN generating without the variable
    result = _generate(base, {}, tracking_file)

    # THEN the whole array key is absent
    assert "tags" not in result
    assert result["name"] == "Server"


def test_emptied_container_is_pruned(tmp_path: Path) -> None:
    # GIVEN a settings object holding only a stale tracked key
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("gameSettings", "onlyKey")}))
    base = {"gameSettings": {"onlyKey": 1}, "name": "Server"}

    # WHEN generating without the variable
    result = _generate(base, {}, tracking_file)

    # THEN the emptied object itself is absent
    assert "gameSettings" not in result
    assert result["name"] == "Server"


def test_pre_existing_empty_container_survives(tmp_path: Path) -> None:
    # GIVEN a base holding an already empty untracked object and a stale key elsewhere
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("slotCount",)}))
    base: dict[str, Any] = {"slotCount": 8, "gameSettings": {}, "name": "Server"}

    # WHEN generating without the stale variable
    result = _generate(base, {}, tracking_file)

    # THEN the pre-existing empty object is retained
    assert "slotCount" not in result
    assert result["gameSettings"] == {}


def test_name_keyed_group_removal(tmp_path: Path) -> None:
    # GIVEN two tracked name-keyed groups and only one group's variables remain
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(
        tracking_file,
        frozenset(
            {
                ("userGroups", "admin", "password"),
                ("userGroups", "admin", "canKickBan"),
                ("userGroups", "guest", "password"),
            }
        ),
    )
    base = {
        "userGroups": [
            {"name": "admin", "password": "old", "canKickBan": True},
            {"name": "guest", "password": "old"},
        ]
    }

    # WHEN generating with only the remaining group's variables
    result = _generate(base, {"ENSHROUDED_USER_GROUPS__GUEST__PASSWORD": "new"}, tracking_file)

    # THEN only the remaining group is present with its current values
    assert result["userGroups"] == [{"name": "guest", "password": "new"}]


def test_untracked_key_inside_group_survives(tmp_path: Path) -> None:
    # GIVEN a group entry holding a never-tracked key plus a tracked password
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("userGroups", "admin", "password")}))
    base = {"userGroups": [{"name": "admin", "password": "old", "keepMe": 42}]}

    # WHEN generating without any group variables
    result = _generate(base, {}, tracking_file)

    # THEN the untracked key and group identity survive and only the password is gone
    assert result["userGroups"] == [{"name": "admin", "keepMe": 42}]


def test_no_history_keeps_existing_keys(tmp_path: Path) -> None:
    # GIVEN a persisted key with no tracking file
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    base = {"slotCount": 8}

    # WHEN generating without any variable setting that key
    result = _generate(base, {}, tracking_file)

    # THEN the key is retained
    assert result["slotCount"] == 8


def test_unusable_tracking_file_removes_nothing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a tracking file that cannot be read as a valid record
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    tracking_file.write_text("not json")
    base = {"slotCount": 8}

    # WHEN generating with the unusable record
    with caplog.at_level("WARNING", logger="enshctl.tracking"):
        result = _generate(base, {}, tracking_file)

    # THEN a warning is logged and the key is retained
    assert result["slotCount"] == 8
    assert "unusable" in caplog.text


def test_unsupported_version_removes_nothing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a tracking file carrying an unsupported version
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    tracking_file.write_text(json.dumps({"version": 999, "paths": [["slotCount"]]}))
    base = {"slotCount": 8}

    # WHEN generating with the unsupported record
    with caplog.at_level("WARNING", logger="enshctl.tracking"):
        result = _generate(base, {}, tracking_file)

    # THEN no key is removed and a warning is logged
    assert result["slotCount"] == 8
    assert "unusable" in caplog.text


def test_invalid_utf8_tracking_file_removes_nothing(tmp_path: Path) -> None:
    # GIVEN a tracking file with invalid UTF-8 bytes
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    tracking_file.write_bytes(b"\xff\xfe invalid")

    # WHEN generating with the undecodable record
    result = _generate({"slotCount": 8}, {}, tracking_file)

    # THEN generation succeeds and the key is retained
    assert result["slotCount"] == 8


def test_missing_persisted_config_resets_tracking(tmp_path: Path) -> None:
    # GIVEN a tracking file naming an Example key but no persisted config
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("slotCount",)}))
    base = {"slotCount": 16}

    # WHEN generating with an Example-supplied base
    result = _generate(base, {}, tracking_file, is_persisted=False)

    # THEN the Example value is retained
    assert result["slotCount"] == 16


def test_write_records_paths_without_values(tmp_path: Path) -> None:
    # GIVEN a group password set from the environment
    from unittest.mock import patch

    tracking_file = tmp_path / ".enshrouded-tracked.json"
    written: list[dict[str, Any]] = []

    def capture(config: dict[str, Any], **_kwargs: object) -> None:
        written.append(deepcopy(config))

    with (
        patch("enshctl.config.environ", {"ENSHROUDED_USER_GROUPS__ADMIN__PASSWORD": "secret-value"}),
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config", side_effect=capture),
    ):
        # WHEN writing the Generated config
        write_generated_config(_settings(), tracking_file=tracking_file, is_persisted=False)

    # THEN the tracking file records the path and does not contain the value
    raw = tracking_file.read_text()
    assert "password" in raw
    assert "secret-value" not in raw
    assert read_tracked_paths(tracking_file) == frozenset({("userGroups", "admin", "password")})


def test_preview_does_not_change_tracking_file(tmp_path: Path) -> None:
    # GIVEN a tracking file recording a stale key
    tracking_file = tmp_path / ".enshrouded-tracked.json"
    write_tracked_paths(tracking_file, frozenset({("slotCount",)}))
    base = {"slotCount": 8}
    before = tracking_file.read_bytes()

    # WHEN generating (preview) without writing
    result = _generate(base, {}, tracking_file)

    # THEN the preview shows the stale key removed and the record is unchanged
    assert "slotCount" not in result
    assert tracking_file.read_bytes() == before


def test_tracking_write_failure_keeps_generated_config(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a generated config write with an unwritable tracking path
    from unittest.mock import patch

    tracking_file = tmp_path / ".enshrouded-tracked.json"
    written: list[dict[str, Any]] = []

    def capture(config: dict[str, Any], **_kwargs: object) -> None:
        written.append(deepcopy(config))

    with (
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config", side_effect=capture),
        patch(
            "enshctl.config.write_tracked_paths",
            side_effect=OSError("unwritable"),
        ),
        caplog.at_level("WARNING", logger="enshctl.config"),
    ):
        # WHEN writing the Generated config
        write_generated_config(_settings(), tracking_file=tracking_file, is_persisted=False)

    # THEN the Generated config remains written and a warning is logged
    assert len(written) == 1
    assert "tracking file" in caplog.text


def test_write_records_object_and_array_keys(tmp_path: Path) -> None:
    # GIVEN env vars setting a JSON object and a JSON array
    from unittest.mock import patch

    tracking_file = tmp_path / ".enshrouded-tracked.json"

    with (
        patch(
            "enshctl.config.environ",
            {
                "ENSHROUDED_GAME_SETTINGS": '{"a": 1, "b": 2}',
                "ENSHROUDED_TAGS": '["English", "Exploration"]',
            },
        ),
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config"),
    ):
        # WHEN writing the Generated config
        write_generated_config(_settings(), tracking_file=tracking_file, is_persisted=False)

    # THEN the object decomposes to per-key paths and the array records as one key
    assert read_tracked_paths(tracking_file) == frozenset(
        {
            ("gameSettings", "a"),
            ("gameSettings", "b"),
            ("tags",),
        }
    )


def test_write_skips_group_name_identity(tmp_path: Path) -> None:
    # GIVEN env vars setting a group password and an explicit group name
    from unittest.mock import patch

    tracking_file = tmp_path / ".enshrouded-tracked.json"
    base: dict[str, Any] = {"userGroups": [{"name": "admin", "password": "old"}]}

    with (
        patch(
            "enshctl.config.environ",
            {
                "ENSHROUDED_USER_GROUPS__ADMIN__PASSWORD": "new",
                "ENSHROUDED_USER_GROUPS__ADMIN__NAME": "admin",
            },
        ),
        patch("enshctl.config.load_base_config", return_value=deepcopy(base)),
        patch("enshctl.config.write_config"),
    ):
        # WHEN writing the Generated config
        write_generated_config(_settings(), tracking_file=tracking_file, is_persisted=False)

    # THEN the password is tracked and the identity name is not
    assert read_tracked_paths(tracking_file) == frozenset({("userGroups", "admin", "password")})


def test_write_forwards_ownership_ids(tmp_path: Path) -> None:
    # GIVEN a writer with custom ownership identifiers
    from dataclasses import replace
    from unittest.mock import patch

    tracking_file = tmp_path / ".enshrouded-tracked.json"
    settings = replace(_settings(), puid=1234, pgid=5678)

    with (
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config"),
        patch("enshctl.tracking.chown") as mocked_chown,
    ):
        # WHEN writing the Generated config
        write_generated_config(settings, tracking_file=tracking_file, is_persisted=False)

    # THEN the tracking file is owned by the configured identifiers
    mocked_chown.assert_called_once_with(tracking_file, 1234, 5678)


def test_write_uses_default_tracking_file() -> None:
    # GIVEN a writer relying on the default tracking location
    from unittest.mock import patch

    from enshctl.paths import TRACKING_FILE

    empty: dict[str, str] = {}
    with (
        patch("enshctl.config.environ", empty),
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config"),
        patch("enshctl.config.write_tracked_paths") as mocked_write,
    ):
        # WHEN writing the Generated config without an explicit tracking path
        write_generated_config(_settings(), is_persisted=False)

    # THEN the record is written to the default sidecar location
    mocked_write.assert_called_once_with(
        TRACKING_FILE,
        frozenset(),
        puid=1000,
        pgid=1000,
    )
