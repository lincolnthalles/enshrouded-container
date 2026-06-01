"""Dynamic Enshrouded server config generation from environment variables."""

import json
import logging
import re
from contextlib import suppress
from os import chown, environ
from typing import Any

from enshctl.settings import CONFIG_FILE, GAME_CONFIG_EXAMPLE, LOG_DIR, OUTPUT_CONFIG, SAVE_DIR

logger = logging.getLogger(__name__)

DEFAULT_SAVE_DIR = "/data/saves"
DEFAULT_LOG_DIR = "/data/logs"


def snake_to_camel(name: str) -> str:
    segments = name.lower().split("_")
    return segments[0] + "".join(s.capitalize() for s in segments[1:])


def parse_value(raw: str) -> bool | int | float | list[Any] | dict[str, Any] | str:
    stripped = raw.strip()

    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False

    if re.match(r"^-?\d+$", stripped):
        return int(stripped)

    if re.match(r"^-?\d+\.\d+([eE][+-]?\d+)?$", stripped):
        return float(stripped)

    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    return stripped


def _is_array_index(segment: str) -> bool:
    """Check if a segment is a non-negative integer (array index)."""
    return segment.isdigit()


def _ensure_list_at(parent: dict[str, Any] | list[Any], key: str) -> list[Any]:
    """Ensure parent[key] is a list, creating it if needed."""
    if isinstance(parent, list):
        idx = int(key)
        while len(parent) <= idx:
            parent.append({})
        return parent[idx]
    if key not in parent or not isinstance(parent[key], list):
        parent[key] = []
    return parent[key]


def _set_at(container: dict[str, Any] | list[Any], key: str, value: object) -> None:
    """Set a value at container[key], handling both dicts and lists."""
    if isinstance(container, list):
        idx = int(key)
        while len(container) <= idx:
            container.append({})
        container[idx] = value
    else:
        container[key] = value


def env_to_dict() -> dict[str, Any]:
    """Parse ENSHROUDED_* env vars into a nested dict.

    Supports nested keys via double underscores (__):
      ENSHROUDED_GAME_SETTINGS__IS_PVP=true -> {"gameSettings": {"isPVP": true}}

    Supports array indexing via numeric segments:
      ENSHROUDED_USER_GROUPS__0__NAME=Admin -> {"userGroups": [{"name": "Admin"}]}

    Non-numeric segments that look like name-keyed dicts are handled later
    by _resolve_array_overrides (edge case for userGroups-style config).
    """
    result: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.upper().startswith("ENSHROUDED_"):
            continue
        stripped = key.removeprefix("ENSHROUDED_").removeprefix("enshrouded_")
        if not stripped:
            continue

        parsed = parse_value(value)
        segments = stripped.split("__")
        camel_path = [snake_to_camel(seg) for seg in segments]

        current: Any = result
        for i, segment in enumerate(camel_path):
            if i == len(camel_path) - 1:
                _set_at(current, segment, parsed)
            elif isinstance(current, list) or _is_array_index(segments[i + 1]):
                current = _ensure_list_at(current, segment)
            else:
                current = current.setdefault(segment, {})
    return result


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = {**base}
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_base_config() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        logger.info("Loading base config from %s", CONFIG_FILE)
        return json.loads(CONFIG_FILE.read_text())

    if GAME_CONFIG_EXAMPLE.exists():
        logger.info("No user config found, extracting defaults from %s", GAME_CONFIG_EXAMPLE)
        return json.loads(GAME_CONFIG_EXAMPLE.read_text())

    logger.warning("No base config found, starting from empty config")
    return {}


def _is_name_keyed_dict(d: dict[str, Any]) -> bool:
    """Check if a dict looks like a name-keyed dict (all values are dicts)."""
    return len(d) > 0 and all(isinstance(v, dict) for v in d.values())


def _resolve_array_overrides(base: dict[str, Any], merged: dict[str, Any]) -> None:
    """Convert name-keyed dicts to arrays (edge case for userGroups-style config).

    Handles the pattern where env vars use group names as keys:
      ENSHROUDED_USER_GROUPS__ADMIN__PASSWORD=Admino
    which produces {"userGroups": {"admin": {"password": "Admino"}}}
    and converts it to:
      {"userGroups": [{"name": "admin", "password": "Admino"}]}

    Triggers when the base config has a list at that key, or when there is
    no base hint and the merged value clearly looks like a name-keyed dict.
    """
    for key in list(merged.keys()):
        merged_val = merged[key]
        base_val = base.get(key)
        is_dict = isinstance(merged_val, dict)
        if not is_dict:
            continue
        if isinstance(base_val, list) or (key not in base and _is_name_keyed_dict(merged_val)):
            merged[key] = [{**v, "name": k} for k, v in merged_val.items()]
        elif isinstance(base_val, dict):
            _resolve_array_overrides(base_val, merged_val)


def set_defaults(config: dict[str, Any]) -> None:
    if "saveDirectory" not in config:
        config["saveDirectory"] = str(SAVE_DIR)
    if "logDirectory" not in config:
        config["logDirectory"] = str(LOG_DIR)


def generate_config() -> dict[str, Any]:
    base = load_base_config()
    overrides = env_to_dict()
    config = deep_merge(base, overrides)
    _resolve_array_overrides(base, config)
    set_defaults(config)
    return config


def write_config(config: dict[str, Any], *, puid: int = 1000, pgid: int = 1000) -> None:
    OUTPUT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CONFIG.write_text(json.dumps(config, indent=2))
    with suppress(OSError):
        chown(OUTPUT_CONFIG, puid, pgid)
    logger.info("Config written to %s", OUTPUT_CONFIG)
