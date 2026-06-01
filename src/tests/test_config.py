"""Tests for config module."""

from os import environ
from typing import cast

from enshctl.config import (
    _resolve_array_overrides,
    deep_merge,
    env_to_dict,
    parse_value,
    snake_to_camel,
)


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
    base: dict = {"name": "Base"}
    override = {"port": 9999}
    result = deep_merge(base, override)
    assert result["name"] == "Base"
    assert result["port"] == 9999


def test_env_to_dict_simple() -> None:
    environ["ENSHROUDED_NAME"] = "Test Server"
    try:
        result = env_to_dict()
        assert result["name"] == "Test Server"
    finally:
        del environ["ENSHROUDED_NAME"]


def test_env_to_dict_snake_case_key() -> None:
    environ["ENSHROUDED_SLOT_COUNT"] = "8"
    try:
        result = env_to_dict()
        assert result["slotCount"] == 8
    finally:
        del environ["ENSHROUDED_SLOT_COUNT"]


def test_env_to_dict_nested() -> None:
    environ["ENSHROUDED_GAME_SETTINGS__IS_PVP"] = "true"
    try:
        result = env_to_dict()
        assert result["gameSettings"]["isPvp"] is True
    finally:
        del environ["ENSHROUDED_GAME_SETTINGS__IS_PVP"]


def test_env_to_dict_ignores_non_enshrouded() -> None:
    environ["SERVER_NAME"] = "ignored"
    try:
        result = env_to_dict()
        assert "serverName" not in result
    finally:
        del environ["SERVER_NAME"]


def test_resolve_array_overrides() -> None:

    base = {"userGroups": [{"name": "default"}], "bans": []}
    merged = {
        "userGroups": {
            "admin": {"password": "AdminXXXXXXXX", "canKickBan": True},
            "friend": {"password": "FriendXXXXXXXX", "canKickBan": False},
        },
        "bans": [],
    }
    _resolve_array_overrides(base, merged)
    assert len(merged["userGroups"]) == 2
    groups = {g["name"]: g for g in cast("list", merged["userGroups"])}
    assert groups["admin"]["password"] == "AdminXXXXXXXX"
    assert groups["admin"]["canKickBan"] is True
    assert groups["friend"]["password"] == "FriendXXXXXXXX"
    assert groups["friend"]["canKickBan"] is False
    assert merged["bans"] == []


def test_resolve_array_overrides_nested() -> None:
    base = {"outer": {"items": []}}
    merged: dict = {"outer": {"items": {"a": {"value": 1}, "b": {"value": 2}}}}
    _resolve_array_overrides(base, merged)
    items = merged["outer"]["items"]
    assert len(items) == 2
    by_name = {i["name"]: i for i in cast("dict", items)}
    assert by_name["a"]["value"] == 1
    assert by_name["b"]["value"] == 2
