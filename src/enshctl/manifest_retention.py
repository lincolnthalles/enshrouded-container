"""Manifest install retention — activation record, pruning, and reclamation."""

import json
import logging
import os
import shutil
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from enshctl import files
from enshctl.manifests import is_latest_tracking
from enshctl.paths import GAME_TREE_DIR, MANIFESTS_DIR, STATUS_FILE

if TYPE_CHECKING:
    from enshctl.settings import AppSettings

logger = logging.getLogger(__name__)

ACTIVATION_RECORD_NAME = ".manifest-history"
PRUNE_DIR_NAME = ".prune"

# _PRUNE_LOCK guards fast `.prune` state changes: directory creation, listing
# snapshots, and renames. _DELETE_LOCK serializes content deletion. Staging
# never waits on _DELETE_LOCK except to remove a stale collision, and cleanup
# waits on it so the free-space evaluation sees the reclaimed bytes.
_PRUNE_LOCK = threading.RLock()
_DELETE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ActivationRecord:
    """Persisted Active Manifest and the Manifest that was Active before it."""

    active: str
    previous: str | None = None


@dataclass(frozen=True)
class ManifestInstall:
    """One complete numeric Manifest install directory."""

    manifest_id: str
    path: Path
    installed_mtime_ns: int


def _activation_record_path(manifests_dir: Path) -> Path:
    return manifests_dir / ACTIVATION_RECORD_NAME


def _is_manifest_id(value: str) -> bool:
    return bool(value) and value.isascii() and value.isdigit()


def read_activation_record(manifests_dir: Path = MANIFESTS_DIR) -> ActivationRecord | None:
    """Read the activation record, treating missing, unreadable, or malformed data as absent."""
    path = _activation_record_path(manifests_dir)
    if path.is_symlink():
        logger.warning("Skipping symlinked activation record %s", path)
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Could not read activation record %s: %s", path, exc)
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        logger.warning("Malformed activation record %s; treating it as absent", path)
        return None
    if not isinstance(payload, dict):
        logger.warning("Malformed activation record %s; treating it as absent", path)
        return None
    active = payload.get("active")
    previous = payload.get("previous")
    if not isinstance(active, str) or not _is_manifest_id(active):
        logger.warning("Malformed activation record %s; treating it as absent", path)
        return None
    if previous is not None and (not isinstance(previous, str) or not _is_manifest_id(previous) or previous == active):
        logger.warning("Malformed activation record %s; treating it as absent", path)
        return None
    return ActivationRecord(active=active, previous=cast("str | None", previous))


def _write_activation_record(record: ActivationRecord, manifests_dir: Path) -> None:
    path = _activation_record_path(manifests_dir)
    if path.is_symlink():
        msg = f"refusing to replace symlinked activation record {path}"
        raise OSError(msg)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    payload = {"active": record.active, "previous": record.previous}
    content = f"{json.dumps(payload, sort_keys=True)}\n".encode()
    files.write_bytes_atomic(path, content)


def record_activation(manifests_dir: Path, active_id: str) -> ActivationRecord | None:
    """Persist the activation record after preparation; return None when the write fails."""
    path = _activation_record_path(manifests_dir)
    if path.is_symlink():
        logger.warning("Refusing to replace symlinked activation record %s", path)
        return None
    existing = read_activation_record(manifests_dir)
    if existing is not None and existing.active == active_id:
        record = existing
    else:
        previous = existing.active if existing is not None and existing.active != active_id else None
        record = ActivationRecord(active=active_id, previous=previous)
    try:
        _write_activation_record(record, manifests_dir)
    except OSError as exc:
        logger.warning("Could not update activation record in %s: %s", manifests_dir, exc)
        return None
    return record


def _complete_installs(manifests_dir: Path) -> tuple[ManifestInstall, ...]:
    if not manifests_dir.exists():
        return ()
    try:
        entries = tuple(manifests_dir.iterdir())
    except OSError as exc:
        logger.warning("Could not list Manifest installs in %s: %s", manifests_dir, exc)
        return ()
    installs: list[ManifestInstall] = []
    for entry in entries:
        if not _is_manifest_id(entry.name):
            continue
        if entry.is_symlink():
            logger.warning("Skipping symlinked Manifest install directory %s", entry)
            continue
        marker = entry / STATUS_FILE
        try:
            if not entry.is_dir():
                continue
            if marker.is_symlink() or not marker.is_file():
                logger.warning("Skipping incomplete Manifest install %s", entry)
                continue
            mtime_ns = marker.stat(follow_symlinks=False).st_mtime_ns
        except OSError as exc:
            logger.warning("Skipping unreadable Manifest install %s: %s", entry, exc)
            continue
        installs.append(ManifestInstall(manifest_id=entry.name, path=entry, installed_mtime_ns=mtime_ns))
    return tuple(installs)


def _most_recent_other(installs: tuple[ManifestInstall, ...], *, excluded: set[str]) -> ManifestInstall | None:
    candidates = [install for install in installs if install.manifest_id not in excluded]
    if not candidates:
        return None
    return max(candidates, key=lambda install: (install.installed_mtime_ns, int(install.manifest_id)))


def _retained_ids(
    installs: tuple[ManifestInstall, ...],
    *,
    active_id: str | None,
    previous_id: str | None,
    extra_keep: frozenset[str] = frozenset(),
) -> frozenset[str]:
    keep = set(extra_keep)
    if active_id is not None:
        keep.add(active_id)
    complete_ids = {install.manifest_id for install in installs}
    if previous_id is not None and previous_id != active_id and previous_id in complete_ids:
        keep.add(previous_id)
    else:
        fallback = _most_recent_other(installs, excluded=keep)
        if fallback is not None:
            keep.add(fallback.manifest_id)
    return frozenset(keep)


def _prune_directory(manifests_dir: Path, *, create: bool) -> Path | None:
    prune_dir = manifests_dir / PRUNE_DIR_NAME
    if prune_dir.is_symlink():
        logger.warning("Skipping Manifest deletion: %s is a symbolic link", prune_dir)
        return None
    if prune_dir.exists() and not prune_dir.is_dir():
        logger.warning("Skipping Manifest deletion: %s is not a directory", prune_dir)
        return None
    if not prune_dir.exists():
        if not create:
            return None
        try:
            prune_dir.mkdir(parents=True)
        except OSError as exc:
            logger.warning("Could not create Manifest deletion staging directory %s: %s", prune_dir, exc)
            return None
    return prune_dir


def _add_owner_write(path: Path) -> None:
    with suppress(OSError):
        mode = path.stat(follow_symlinks=False).st_mode
        path.chmod((mode & 0o7777) | 0o700)


def _make_dirs_writable(root: Path) -> None:
    _add_owner_write(root)
    for current, directories, _files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in directories:
            child = current_path / name
            if child.is_symlink():
                continue
            _add_owner_write(child)


def _remove_path(path: Path) -> None:
    if not path.parent.is_symlink():
        _add_owner_write(path.parent)
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
        return
    _make_dirs_writable(path)
    shutil.rmtree(path)


def _list_staged_entries(prune_dir: Path) -> tuple[Path, ...]:
    try:
        return tuple(prune_dir.iterdir())
    except OSError as exc:
        logger.warning("Could not list Manifest deletion staging directory %s: %s", prune_dir, exc)
        return ()


def _delete_entries(entries: tuple[Path, ...], stop_event: threading.Event | None = None) -> None:
    for entry in entries:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            _remove_path(entry)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("Could not remove staged Manifest data %s: %s", entry, exc)


def _snapshot_prune_entries(manifests_dir: Path) -> tuple[Path, ...]:
    try:
        with _PRUNE_LOCK:
            if not manifests_dir.exists():
                return ()
            prune_dir = _prune_directory(manifests_dir, create=False)
            if prune_dir is None:
                return ()
            return _list_staged_entries(prune_dir)
    except OSError as exc:
        logger.warning("Could not snapshot Manifest deletion staging in %s: %s", manifests_dir, exc)
        return ()


def _rename_for_deletion(source: Path, destination: Path) -> None:
    original_mode: int | None = None
    try:
        original_mode = source.stat(follow_symlinks=False).st_mode & 0o7777
        source.chmod(original_mode | 0o700)
        source.rename(destination)
    except OSError:
        if original_mode is not None:
            try:
                source.chmod(original_mode)
            except OSError as exc:
                logger.warning("Could not restore permissions on %s after failed staging: %s", source, exc)
        raise


def _delete_prune_contents(manifests_dir: Path, stop_event: threading.Event | None = None) -> None:
    with _DELETE_LOCK:
        _delete_entries(_snapshot_prune_entries(manifests_dir), stop_event)


def cleanup_prune_dir(manifests_dir: Path = MANIFESTS_DIR) -> None:
    """Remove every entry under `.prune`, leaving the staging directory itself in place."""
    _delete_prune_contents(manifests_dir)


def _stage_candidates(manifests_dir: Path, candidates: tuple[ManifestInstall, ...]) -> tuple[Path, ...]:
    with _PRUNE_LOCK:
        prune_dir = _prune_directory(manifests_dir, create=True)
        if prune_dir is None:
            return ()
        pairs = tuple((install, prune_dir / install.manifest_id) for install in candidates)
        collisions = tuple(dest for _, dest in pairs if dest.exists() or dest.is_symlink())
    if collisions:
        with _DELETE_LOCK:
            _delete_entries(collisions)
    with _PRUNE_LOCK:
        prune_dir = _prune_directory(manifests_dir, create=True)
        if prune_dir is None:
            return ()
        staged: list[Path] = []
        for install, destination in pairs:
            try:
                if destination.exists() or destination.is_symlink():
                    logger.warning(
                        "Could not stage Manifest install %s for deletion: destination %s exists",
                        install.path,
                        destination,
                    )
                    continue
                _rename_for_deletion(install.path, destination)
            except OSError as exc:
                logger.warning("Could not stage Manifest install %s for deletion: %s", install.path, exc)
                continue
            staged.append(destination)
        return tuple(staged)


def _background_delete(manifests_dir: Path, stop_event: threading.Event | None) -> None:
    _delete_prune_contents(manifests_dir, stop_event)


def delete_prune_contents_in_background(
    manifests_dir: Path = MANIFESTS_DIR,
    stop_event: threading.Event | None = None,
) -> threading.Thread | None:
    """Delete staged Manifest data on a daemon thread, returning None when the thread cannot start."""
    thread = threading.Thread(
        target=_background_delete,
        args=(manifests_dir, stop_event),
        daemon=True,
        name="manifest-prune",
    )
    try:
        thread.start()
    except (OSError, RuntimeError) as exc:
        logger.warning("Could not start Manifest deletion in %s: %s", manifests_dir, exc)
        return None
    return thread


def _game_tree_manifest_ids(game_tree_dir: Path, manifests_dir: Path) -> frozenset[str]:
    if game_tree_dir.is_symlink() or not game_tree_dir.is_dir():
        return frozenset()
    try:
        base = manifests_dir.resolve(strict=False)
    except OSError, RuntimeError, ValueError:
        base = manifests_dir
    manifest_ids: set[str] = set()
    try:
        entries = tuple(game_tree_dir.rglob("*"))
    except OSError as exc:
        logger.warning("Could not inspect Game tree %s: %s", game_tree_dir, exc)
        return frozenset()
    for entry in entries:
        if not entry.is_symlink():
            continue
        try:
            target = entry.resolve(strict=False)
            relative = target.relative_to(base)
        except OSError, RuntimeError, ValueError:
            continue
        if len(relative.parts) >= 2 and _is_manifest_id(relative.parts[0]):
            manifest_ids.add(relative.parts[0])
    if len(manifest_ids) > 1:
        logger.warning(
            "Game tree %s links multiple Manifest installs; keeping every linked install",
            game_tree_dir,
        )
    return frozenset(manifest_ids)


def _stage_pruning(manifests_dir: Path, activation: ActivationRecord) -> tuple[Path, ...]:
    """Stage complete installs outside the Active and Previous Active installs for deletion."""
    installs = _complete_installs(manifests_dir)
    keep = _retained_ids(installs, active_id=activation.active, previous_id=activation.previous)
    candidates = tuple(install for install in installs if install.manifest_id not in keep)
    return _stage_candidates(manifests_dir, candidates)


def reclaim_for_download(
    manifests_dir: Path,
    *,
    requested_id: str,
    game_tree_dir: Path = GAME_TREE_DIR,
) -> tuple[Path, ...]:
    """Delete complete installs outside the reclamation keep set synchronously."""
    activation = read_activation_record(manifests_dir)
    active_id = activation.active if activation is not None else None
    previous_id = activation.previous if activation is not None else None
    game_tree_ids = _game_tree_manifest_ids(game_tree_dir, manifests_dir)
    extra_keep = {requested_id} | set(game_tree_ids)
    installs = _complete_installs(manifests_dir)
    keep = _retained_ids(
        installs,
        active_id=active_id,
        previous_id=previous_id,
        extra_keep=frozenset(extra_keep),
    )
    candidates = tuple(install for install in installs if install.manifest_id not in keep)
    staged = _stage_candidates(manifests_dir, candidates)
    _delete_prune_contents(manifests_dir)
    return staged


def retain_after_start(
    settings: AppSettings,
    active_id: str,
    stop_event: threading.Event,
    *,
    manifests_dir: Path = MANIFESTS_DIR,
) -> threading.Thread | None:
    """Record the Active Manifest and start deletion of installs outside the keep set."""
    activation = record_activation(manifests_dir, active_id)
    if activation is None or not settings.manifest_prune_enabled or not is_latest_tracking(settings.version):
        return None
    staged = _stage_pruning(manifests_dir, activation)
    if not staged:
        return None
    return delete_prune_contents_in_background(manifests_dir, stop_event)
