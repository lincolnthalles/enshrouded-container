"""Tests for config module."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from enshctl.config import (
    _resolve_array_overrides,
    deep_merge,
    env_to_dict,
    generate_config,
    generated_save_directories,
    parse_value,
    snake_to_camel,
    write_generated_config,
)
from enshctl.paths import SAVE_DIR
from enshctl.settings import AppSettings


def _settings(backup_dir: Path = Path("/data/backups")) -> AppSettings:
    return AppSettings(backup_dir=str(backup_dir))


def _read_save_dir(config_path: Path, *, backup_dir: Path = Path("/data/backups")) -> Path:
    return generated_save_directories(config_path, settings=_settings(backup_dir)).saves_dir


def test_snake_to_camel_single() -> None:
    assert snake_to_camel("NAME") == "name"
    assert snake_to_camel("name") == "name"


def test_snake_to_camel_multi() -> None:
    assert snake_to_camel("GAME_SETTINGS") == "gameSettings"
    assert snake_to_camel("PLAYER_HEALTH_FACTOR") == "playerHealthFactor"


def test_parse_value_bool() -> None:
    assert parse_value("true") is True
    assert parse_value("false") is False
    assert parse_value("TRUE") is True
    assert parse_value("FALSE") is False


def test_parse_value_int() -> None:
    assert parse_value("42") == 42
    assert parse_value("-1") == -1
    assert parse_value("0") == 0


def test_parse_value_float() -> None:
    assert parse_value("1.5") == 1.5
    assert parse_value("-0.5") == -0.5


def test_parse_value_string() -> None:
    assert parse_value("hello") == "hello"
    assert parse_value("My Server Name") == "My Server Name"


def test_parse_value_json_array() -> None:
    result = parse_value('["sword","shield"]')
    assert result == ["sword", "shield"]


def test_parse_value_json_object() -> None:
    result = parse_value('{"key": "value"}')
    assert result == {"key": "value"}


def test_deep_merge_override() -> None:
    base = {"name": "Base", "port": 15636}
    override = {"name": "Override"}
    result = deep_merge(base, override)
    assert result["name"] == "Override"
    assert result["port"] == 15636


def test_deep_merge_nested() -> None:
    base = {"gameSettings": {"isPVP": False, "slots": 4}}
    override = {"gameSettings": {"isPVP": True}}
    result = deep_merge(base, override)
    assert result["gameSettings"]["isPVP"] is True
    assert result["gameSettings"]["slots"] == 4


def test_deep_merge_new_key() -> None:
    base: dict[str, Any] = {"name": "Base"}
    override = {"port": 9999}
    result = deep_merge(base, override)
    assert result["name"] == "Base"
    assert result["port"] == 9999


def test_env_to_dict_without_source_reads_process_environment() -> None:
    from unittest.mock import patch

    # GIVEN a process environment carrying an ENSHROUDED_* value
    with patch("enshctl.config.environ", {"ENSHROUDED_NAME": "Ambient"}):
        # WHEN parsing without an explicit mapping
        result = env_to_dict()
    # THEN the ambient value is used
    assert result["name"] == "Ambient"


def test_env_to_dict_with_explicit_source_ignores_process_environment() -> None:
    from unittest.mock import patch

    # GIVEN ambient and explicit values that differ
    with patch(
        "enshctl.config.environ",
        {"ENSHROUDED_NAME": "Ambient", "ENSHROUDED_SAVE_DIRECTORY": "/ambient/saves"},
    ):
        # WHEN parsing an explicit mapping
        result = env_to_dict({"ENSHROUDED_NAME": "Explicit"})
    # THEN only the supplied mapping contributes
    assert result == {"name": "Explicit"}


def test_env_to_dict_ignores_empty_prefix_remainder() -> None:
    # GIVEN a prefixed variable whose remainder is empty
    # WHEN parsing it
    # THEN it does not produce a config key
    assert env_to_dict({"ENSHROUDED_": "ignored"}) == {}


def test_env_to_dict_simple() -> None:
    result = env_to_dict({"ENSHROUDED_NAME": "Test Server"})
    assert result["name"] == "Test Server"


def test_env_to_dict_snake_case_key() -> None:
    result = env_to_dict({"ENSHROUDED_SLOT_COUNT": "8"})
    assert result["slotCount"] == 8


def test_env_to_dict_nested() -> None:
    result = env_to_dict({"ENSHROUDED_GAME_SETTINGS__IS_PVP": "true"})
    assert result["gameSettings"]["isPvp"] is True


def test_env_to_dict_ignores_non_enshrouded() -> None:
    result = env_to_dict({"SERVER_NAME": "ignored"})
    assert result == {}


def test_env_to_dict_mixed_case_prefix() -> None:
    result = env_to_dict({"Enshrouded_MIXED_case_TEST": "1"})
    assert result["mixedCaseTest"] == 1


def test_resolve_array_overrides() -> None:

    base: dict[str, Any] = {"userGroups": [{"name": "default"}], "bans": []}
    merged: dict[str, Any] = {
        "userGroups": {
            "admin": {"password": "AdminXXXXXXXX", "canKickBan": True},
            "friend": {"password": "FriendXXXXXXXX", "canKickBan": False},
        },
        "bans": [],
    }
    _resolve_array_overrides(base, merged)
    assert len(merged["userGroups"]) == 2
    groups = {g["name"]: g for g in cast("list[dict[str, Any]]", merged["userGroups"])}
    assert groups["admin"]["password"] == "AdminXXXXXXXX"
    assert groups["admin"]["canKickBan"] is True
    assert groups["friend"]["password"] == "FriendXXXXXXXX"
    assert groups["friend"]["canKickBan"] is False
    assert merged["bans"] == []


def test_resolve_array_overrides_nested() -> None:
    base: dict[str, Any] = {"outer": {"items": []}}
    merged: dict[str, Any] = {"outer": {"items": {"a": {"value": 1}, "b": {"value": 2}}}}
    _resolve_array_overrides(base, merged)
    items = cast("list[dict[str, Any]]", merged["outer"]["items"])
    assert len(items) == 2
    by_name = {i["name"]: i for i in items}
    assert by_name["a"]["value"] == 1
    assert by_name["b"]["value"] == 2


def test_generated_save_dir_reads_absolute_path(tmp_path: Path) -> None:
    # GIVEN a Generated config naming an absolute save directory
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "/mnt/nfs/saves"}')
    # WHEN resolving the save directory
    # THEN that path is used
    assert _read_save_dir(config_file, backup_dir=Path("/data/backups")) == Path("/mnt/nfs/saves")


def test_generated_save_dir_defaults_when_missing(tmp_path: Path) -> None:
    # GIVEN no Generated config file
    # WHEN resolving the save directory
    # THEN the volume default is used
    assert _read_save_dir(tmp_path / "missing.json", backup_dir=Path("/data/backups")) == SAVE_DIR


def test_generated_save_dir_defaults_when_relative(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a Generated config with a relative save directory
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "saves"}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "not absolute" in caplog.text


def test_generated_save_dir_defaults_when_invalid_json(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN an unreadable Generated config
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text("not json")
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "Could not read Generated config" in caplog.text


def test_generated_save_dir_defaults_when_unsafe(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a Generated config whose save directory overlaps protected data
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "/data"}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "overlaps protected path" in caplog.text


def test_generated_save_dir_defaults_when_root(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a Generated config pointing saves at the filesystem root
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "/"}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "overlaps protected path" in caplog.text


def test_generated_save_dir_defaults_when_unreadable(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN an unreadable Generated config path
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(tmp_path, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "Could not read Generated config" in caplog.text


def test_generated_save_dir_defaults_when_traversal(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a traversal path that resolves onto protected backups
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "/data/saves/../backups"}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "overlaps protected path" in caplog.text


def test_generated_save_dir_defaults_when_double_slash(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN an alias path that resolves onto protected backups
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "//data/backups"}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "overlaps protected path" in caplog.text


def test_generated_save_dir_defaults_when_symlinked_protected(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a symlink whose target is the backups directory
    backups = tmp_path / "backups"
    backups.mkdir()
    link = tmp_path / "saves-link"
    link.symlink_to(backups)
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text(f'{{"saveDirectory": "{link}"}}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=backups)
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "overlaps protected path" in caplog.text


def test_generated_save_dir_warns_for_non_string(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a Generated config with a numeric save directory
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": 123}')
    with caplog.at_level("WARNING", logger="enshctl.config"):
        # WHEN resolving the save directory
        result = _read_save_dir(config_file, backup_dir=Path("/data/backups"))
    # THEN the volume default is used with a warning
    assert result == SAVE_DIR
    assert "not a string" in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"saveDirectory": 123}',
        '{"saveDirectory": "a\\u0000b"}',
        '{"saveDirectory": "/mnt/\\u0000/saves"}',
    ],
)
def test_generated_save_dir_defaults_for_malformed_values(tmp_path: Path, payload: str) -> None:
    # GIVEN a Generated config with a malformed save directory value
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text(payload)
    # WHEN resolving the save directory
    # THEN the volume default is used
    assert _read_save_dir(config_file, backup_dir=Path("/data/backups")) == SAVE_DIR


def test_generated_save_directories_pair_sibling_restore_tmp(tmp_path: Path) -> None:
    # GIVEN a Generated config naming an absolute save directory
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text('{"saveDirectory": "/mnt/nfs/saves"}')

    # WHEN resolving the save locations
    result = generated_save_directories(config_file, settings=_settings())

    # THEN the restore staging directory is a sibling of the save directory
    assert result.saves_dir == Path("/mnt/nfs/saves")
    assert result.restore_tmp_dir == Path("/mnt/nfs/saves-restore-tmp")


@pytest.mark.parametrize(
    "configured",
    [
        "/data",
        "/mnt/\x00/saves",
    ],
)
def test_write_generated_config_resolves_invalid_save_dir_before_write(
    configured: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import patch

    # GIVEN a Generated config whose saveDirectory is protected or malformed
    written: list[dict[str, Any]] = []

    def capture(config: dict[str, Any], **_kwargs: object) -> None:
        written.append(deepcopy(config))

    with (
        patch("enshctl.config.environ", {"ENSHROUDED_SAVE_DIRECTORY": configured}),
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config", side_effect=capture),
        caplog.at_level("WARNING", logger="enshctl.config"),
    ):
        # WHEN writing the Generated config
        result = write_generated_config(_settings())

    # THEN the safe directory is returned and only the safe value is written
    assert result.saves_dir == SAVE_DIR
    assert result.restore_tmp_dir == SAVE_DIR.parent / "saves-restore-tmp"
    assert len(written) == 1
    assert written[0]["saveDirectory"] == str(SAVE_DIR)
    assert "Using save directory" in caplog.text


def test_write_generated_config_preserves_absolute_save_dir(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import patch

    # GIVEN an absolute, non-protected save directory with a trailing separator
    saves = tmp_path / "custom" / "saves"
    configured = f"{saves}/"
    written: list[dict[str, Any]] = []

    def capture(config: dict[str, Any], **_kwargs: object) -> None:
        written.append(deepcopy(config))

    with (
        patch("enshctl.config.environ", {"ENSHROUDED_SAVE_DIRECTORY": configured}),
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config", side_effect=capture),
        caplog.at_level("WARNING", logger="enshctl.config"),
    ):
        # WHEN writing the Generated config
        result = write_generated_config(_settings())

    # THEN the equivalent path is written unchanged without a warning
    assert result.saves_dir == saves
    assert len(written) == 1
    assert written[0]["saveDirectory"] == configured
    assert "Using save directory" not in caplog.text


def test_write_generated_config_round_trips_through_reader(tmp_path: Path) -> None:
    from unittest.mock import patch

    # GIVEN a Generated config whose unsafe saveDirectory resolves before writing
    written: list[dict[str, Any]] = []

    def capture(config: dict[str, Any], **_kwargs: object) -> None:
        written.append(deepcopy(config))

    with (
        patch("enshctl.config.environ", {"ENSHROUDED_SAVE_DIRECTORY": "/data"}),
        patch("enshctl.config.load_base_config", return_value={}),
        patch("enshctl.config.write_config", side_effect=capture),
    ):
        written_dirs = write_generated_config(_settings())

    # WHEN reading the written config back through the consumer path
    config_file = tmp_path / "enshrouded_server.json"
    config_file.write_text(json.dumps(written[0]))
    read_dirs = generated_save_directories(config_file, settings=_settings())

    # THEN the writer and reader agree on the save locations
    assert read_dirs == written_dirs


def test_generate_config_without_source_reads_process_environment() -> None:
    from unittest.mock import patch

    # GIVEN an ambient ENSHROUDED_* value and an empty base config
    with (
        patch("enshctl.config.environ", {"ENSHROUDED_NAME": "Ambient"}),
        patch("enshctl.config.load_base_config", return_value={}),
    ):
        # WHEN generating without an explicit mapping
        result = generate_config()
    # THEN the ambient override is applied
    assert result["name"] == "Ambient"


def test_generate_config_with_explicit_source_ignores_process_environment() -> None:
    from unittest.mock import patch

    # GIVEN ambient values that differ from the supplied mapping
    with (
        patch(
            "enshctl.config.environ",
            {"ENSHROUDED_NAME": "Ambient", "ENSHROUDED_SAVE_DIRECTORY": "/ambient/saves"},
        ),
        patch("enshctl.config.load_base_config", return_value={}),
    ):
        # WHEN generating from an explicit mapping
        result = generate_config({"ENSHROUDED_NAME": "Explicit"})
    # THEN only the supplied mapping contributes
    assert result["name"] == "Explicit"
    assert result["saveDirectory"] == "/data/saves"


def test_generate_config_remaps_relative_save_directory(caplog: pytest.LogCaptureFixture) -> None:
    from unittest.mock import patch

    # GIVEN a base config with a relative saveDirectory
    with (
        patch("enshctl.config.load_base_config", return_value={"saveDirectory": "./savegame"}),
        caplog.at_level("WARNING", logger="enshctl.config"),
    ):
        # WHEN generating the config
        result = generate_config({})
    # THEN it remaps to the volume path with a warning naming the value
    assert result["saveDirectory"] == "/data/saves"
    assert "./savegame" in caplog.text


def test_generate_config_remaps_relative_log_directory() -> None:
    from unittest.mock import patch

    # GIVEN a base config with a relative logDirectory
    with patch("enshctl.config.load_base_config", return_value={"logDirectory": "logs"}):
        # WHEN generating the config
        result = generate_config({})
    # THEN it remaps to the volume path
    assert result["logDirectory"] == "/data/logs"


def test_generate_config_remaps_env_relative_save_directory() -> None:
    from unittest.mock import patch

    # GIVEN a relative save directory in the supplied mapping
    source = {"ENSHROUDED_SAVE_DIRECTORY": "./savegame"}
    with patch("enshctl.config.load_base_config", return_value={}):
        # WHEN generating the config
        result = generate_config(source)
    # THEN the env value is remapped, not passed through
    assert result["saveDirectory"] == "/data/saves"


def test_generate_config_empty_save_directory_falls_back_to_default() -> None:
    from unittest.mock import patch

    # GIVEN an empty save directory in the supplied mapping
    source = {"ENSHROUDED_SAVE_DIRECTORY": ""}
    with patch("enshctl.config.load_base_config", return_value={}):
        # WHEN generating the config
        result = generate_config(source)
    # THEN the default volume path is used, not the empty string
    assert result["saveDirectory"] == "/data/saves"


def test_generate_config_whitespace_base_save_directory_falls_back_to_default() -> None:
    from unittest.mock import patch

    # GIVEN a whitespace-only save directory in the base config
    with patch("enshctl.config.load_base_config", return_value={"saveDirectory": "   "}):
        # WHEN generating the config
        result = generate_config({})
    # THEN the default volume path is used
    assert result["saveDirectory"] == "/data/saves"


def test_generate_config_keeps_absolute_custom_paths() -> None:
    from unittest.mock import patch

    # GIVEN absolute custom paths in the supplied mapping
    source = {
        "ENSHROUDED_SAVE_DIRECTORY": "/mnt/nfs/saves",
        "ENSHROUDED_LOG_DIRECTORY": "/mnt/nfs/logs",
    }
    with patch("enshctl.config.load_base_config", return_value={}):
        # WHEN generating the config
        result = generate_config(source)
    # THEN they pass through untouched
    assert result["saveDirectory"] == "/mnt/nfs/saves"
    assert result["logDirectory"] == "/mnt/nfs/logs"
