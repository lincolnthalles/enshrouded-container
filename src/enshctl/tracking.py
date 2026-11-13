"""Stale env key tracking — the tracking file and stale-key reconciliation."""

import json
import logging
from contextlib import suppress
from copy import deepcopy
from os import chown
from typing import TYPE_CHECKING, Any

from enshctl.files import write_bytes_atomic

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

TRACKING_VERSION = 1

KeyPath = tuple[str | int, ...]


def format_key_path(path: KeyPath) -> str:
    parts: list[str] = []
    for segment in path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        elif parts:
            parts.append(f".{segment}")
        else:
            parts.append(segment)
    return "".join(parts)


def prune_tracked_keys(
    base: dict[str, Any],
    stale: frozenset[KeyPath] | set[KeyPath],
) -> tuple[dict[str, Any], list[KeyPath]]:
    pruned = deepcopy(base)
    removed: list[KeyPath] = []
    ordered = sorted(stale, key=_prune_order, reverse=True)
    for path in ordered:
        if _delete_path(pruned, path):
            removed.append(path)
    return pruned, removed


def _prune_order(path: KeyPath) -> tuple[tuple[int, ...], tuple[tuple[int, int, str], ...]]:
    # Higher numeric indices sort first regardless of where they appear in the
    # path, so that deleting from a list never invalidates a not-yet-deleted
    # lower index. Non-numeric segments only break ties.
    numeric = tuple(sorted((segment for segment in path if isinstance(segment, int)), reverse=True))

    def encode(segment: str | int) -> tuple[int, int, str]:
        if isinstance(segment, int):
            return (0, segment, "")
        return (1, 0, segment)

    return (numeric, tuple(encode(segment) for segment in path))


def _delete_path(root: dict[str, Any], path: KeyPath) -> bool:
    if not path:
        return False
    current: dict[str, Any] | list[Any] = root
    history: list[tuple[dict[str, Any] | list[Any], str | int, bool]] = []
    for segment in path[:-1]:
        if isinstance(current, dict):
            if not isinstance(segment, str) or segment not in current:
                return False
            child = current[segment]
            if not isinstance(child, (dict, list)):
                return False
            history.append((current, segment, False))
            current = child
        elif isinstance(current, list):
            if isinstance(segment, int):
                if not 0 <= segment < len(current):
                    return False
                child = current[segment]
                if not isinstance(child, (dict, list)):
                    return False
                history.append((current, segment, False))
                current = child
            elif isinstance(segment, str):
                index = _find_by_name(current, segment)
                if index is None:
                    return False
                child = current[index]
                if not isinstance(child, (dict, list)):
                    return False
                history.append((current, index, True))
                current = child
            else:
                return False
        else:
            return False
    leaf = path[-1]
    if isinstance(current, dict):
        if not isinstance(leaf, str) or leaf not in current:
            return False
        del current[leaf]
    elif isinstance(current, list):
        if isinstance(leaf, int):
            if not 0 <= leaf < len(current):
                return False
            del current[leaf]
        elif isinstance(leaf, str):
            index = _find_by_name(current, leaf)
            if index is None:
                return False
            del current[index]
        else:
            return False
    else:
        return False
    while history:
        parent, key, is_identity_entry = history[-1]
        if not _is_emptied(current, is_identity_entry):
            break
        history.pop()
        if isinstance(parent, dict):
            if isinstance(key, str):
                parent.pop(key, None)
        elif isinstance(key, int):
            del parent[key]
        current = parent
    return True


def _find_by_name(entries: list[Any], group_name: str) -> int | None:
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("name") == group_name:
            return index
    return None


def _is_emptied(container: dict[str, Any] | list[Any], is_identity_entry: bool) -> bool:
    if isinstance(container, dict):
        if is_identity_entry:
            return not container or (len(container) == 1 and "name" in container)
        return not container
    return not container


def read_tracked_paths(path: Path) -> frozenset[KeyPath] | None:
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None
    except OSError, ValueError:
        logger.warning("Tracking file %s is unusable; keeping existing keys", path)
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        logger.warning("Tracking file %s is unusable; keeping existing keys", path)
        return None
    if (
        not isinstance(record, dict)
        or record.get("version") != TRACKING_VERSION
        or not isinstance(record.get("paths"), list)
    ):
        logger.warning("Tracking file %s is unusable; keeping existing keys", path)
        return None
    paths: set[KeyPath] = set()
    for entry in record["paths"]:
        parsed = _parse_path(entry)
        if parsed is None:
            logger.warning("Tracking file %s is unusable; keeping existing keys", path)
            return None
        paths.add(parsed)
    return frozenset(paths)


def _parse_path(entry: object) -> KeyPath | None:
    if not isinstance(entry, list) or not entry:
        return None
    segments: list[str | int] = []
    for segment in entry:
        if isinstance(segment, str) or (isinstance(segment, int) and not isinstance(segment, bool)):
            segments.append(segment)
        else:
            return None
    return tuple(segments)


def write_tracked_paths(path: Path, paths: frozenset[KeyPath], *, puid: int = 1000, pgid: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = sorted(paths, key=lambda p: json.dumps(list(p)))
    record = {"version": TRACKING_VERSION, "paths": [list(entry) for entry in encoded]}
    write_bytes_atomic(path, json.dumps(record, indent=2).encode())
    with suppress(OSError):
        chown(path, puid, pgid)
