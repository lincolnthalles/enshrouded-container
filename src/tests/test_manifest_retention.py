"""Tests for Manifest activation, pruning, and reclamation."""

import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from enshctl import manifest_retention
from enshctl.manifests import is_latest_tracking
from enshctl.paths import STATUS_FILE
from enshctl.settings import AppSettings


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings(), **overrides)  # type: ignore[arg-type]


def _install(
    manifests_dir: Path,
    manifest_id: str,
    *,
    complete: bool = True,
    mtime_ns: int | None = None,
) -> Path:
    path = manifests_dir / manifest_id
    path.mkdir(parents=True)
    (path / "game.bin").write_bytes(b"game")
    if complete:
        marker = path / STATUS_FILE
        marker.touch()
        if mtime_ns is not None:
            os.utime(marker, ns=(mtime_ns, mtime_ns))
    return path


def _join(thread: threading.Thread | None) -> None:
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive()


def _activate(manifests_dir: Path, *manifest_ids: str) -> manifest_retention.ActivationRecord:
    record: manifest_retention.ActivationRecord | None = None
    for manifest_id in manifest_ids:
        record = manifest_retention.record_activation(manifests_dir, manifest_id)
        assert record is not None
    assert record is not None
    return record


def test_activation_record_tracks_distinct_previous_and_survives_same_active(tmp_path: Path) -> None:
    # GIVEN an empty Manifests directory
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()

    # WHEN recording successive active Manifests and repeating the current one
    assert manifest_retention.record_activation(manifests_dir, "111")
    assert manifest_retention.record_activation(manifests_dir, "222")
    assert manifest_retention.record_activation(manifests_dir, "222")

    # THEN the previous entry holds the last distinct active Manifest
    assert manifest_retention.read_activation_record(manifests_dir) == manifest_retention.ActivationRecord(
        active="222",
        previous="111",
    )


def test_malformed_activation_record_is_treated_as_absent(tmp_path: Path) -> None:
    # GIVEN malformed activation data
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    (manifests_dir / manifest_retention.ACTIVATION_RECORD_NAME).write_text("{not-json")

    # WHEN reading and replacing it
    assert manifest_retention.read_activation_record(manifests_dir) is None
    assert manifest_retention.record_activation(manifests_dir, "333")

    # THEN the replacement record starts without a previous entry
    assert manifest_retention.read_activation_record(manifests_dir) == manifest_retention.ActivationRecord(
        active="333",
        previous=None,
    )


def test_invalid_utf8_activation_record_is_treated_as_absent(tmp_path: Path) -> None:
    # GIVEN an activation record with invalid UTF-8 bytes
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    (manifests_dir / manifest_retention.ACTIVATION_RECORD_NAME).write_bytes(b"\xff\xfe-not-utf8")

    # WHEN reading and replacing it
    assert manifest_retention.read_activation_record(manifests_dir) is None
    assert manifest_retention.record_activation(manifests_dir, "333")

    # THEN the replacement record starts without a previous entry
    assert manifest_retention.read_activation_record(manifests_dir) == manifest_retention.ActivationRecord(
        active="333",
        previous=None,
    )


def test_symlinked_activation_record_is_not_replaced(tmp_path: Path) -> None:
    # GIVEN a symlinked activation record path
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    target = tmp_path / "outside"
    target.write_text("keep")
    (manifests_dir / manifest_retention.ACTIVATION_RECORD_NAME).symlink_to(target)

    # WHEN recording an active Manifest
    assert not manifest_retention.record_activation(manifests_dir, "444")

    # THEN the symlink and its target remain
    assert (manifests_dir / manifest_retention.ACTIVATION_RECORD_NAME).is_symlink()
    assert target.read_text() == "keep"


def test_activation_record_write_failure_skips_pruning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN complete installs and a failing activation-record write
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    _install(manifests_dir, "300")

    def fail_write(_path: Path, _data: bytes) -> None:
        msg = "read-only volume"
        raise OSError(msg)

    monkeypatch.setattr(manifest_retention.files, "write_bytes_atomic", fail_write)

    # WHEN retaining after preparation of Manifest 300
    with caplog.at_level("WARNING", logger="enshctl.manifest_retention"):
        thread = manifest_retention.retain_after_start(
            _settings(version="latest"),
            "300",
            threading.Event(),
            manifests_dir=manifests_dir,
        )

    # THEN pruning is skipped and the record failure is warned
    assert thread is None
    assert (manifests_dir / "100").is_dir()
    assert (manifests_dir / "300").is_dir()
    assert any("Could not update activation record" in record.message for record in caplog.records)


def test_retain_keeps_active_and_recorded_previous_installs(tmp_path: Path) -> None:
    # GIVEN an active Manifest with a recorded previous and older installs
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    for manifest_id in ("100", "200", "300", "400"):
        _install(manifests_dir, manifest_id)
    _activate(manifests_dir, "100", "200")

    # WHEN retaining after preparation of Manifest 200
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "200",
        threading.Event(),
        manifests_dir=manifests_dir,
    )
    _join(thread)

    # THEN the Active and Previous Active installs remain and older installs are staged
    assert (manifests_dir / "100").is_dir()
    assert (manifests_dir / "200").is_dir()
    assert not (manifests_dir / "300").exists()
    assert not (manifests_dir / "400").exists()


def test_first_start_fallback_uses_installed_mtime_then_greatest_id(tmp_path: Path) -> None:
    # GIVEN no activation record and two equally recent complete installs
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100", mtime_ns=1_000)
    _install(manifests_dir, "200", mtime_ns=1_000)
    _install(manifests_dir, "300", mtime_ns=3_000)

    # WHEN retaining after preparation of Manifest 300
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "300",
        threading.Event(),
        manifests_dir=manifests_dir,
    )
    _join(thread)

    # THEN the greatest-id tie-break keeps Manifest 200 as the fallback
    assert (manifests_dir / "200").is_dir()
    assert (manifests_dir / "300").is_dir()
    assert not (manifests_dir / "100").exists()


def test_incomplete_install_survives_with_a_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a numeric install without the `.installed` marker
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    incomplete = manifests_dir / "200"
    incomplete.mkdir()
    (incomplete / "game.bin").write_bytes(b"partial")
    _install(manifests_dir, "300")
    _activate(manifests_dir, "300")

    # WHEN retaining after preparation of Manifest 300
    with caplog.at_level("WARNING", logger="enshctl.manifest_retention"):
        thread = manifest_retention.retain_after_start(
            _settings(version="latest"),
            "300",
            threading.Event(),
            manifests_dir=manifests_dir,
        )
        _join(thread)

    # THEN the incomplete install stays and is named in a warning
    assert incomplete.is_dir()
    assert any("incomplete Manifest install" in record.message for record in caplog.records)


def test_protected_entries_and_symlinks_survive_pruning(tmp_path: Path) -> None:
    # GIVEN protected entries and a symlink in the Manifests directory
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    _install(manifests_dir, "200")
    _install(manifests_dir, "300")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    for name in (".manifest", "depot.keys", ".latest-manifest", "notes"):
        (manifests_dir / name).write_text("control")
    (manifests_dir / "link").symlink_to(outside, target_is_directory=True)
    _activate(manifests_dir, "300")

    # WHEN retaining after preparation of Manifest 300
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "300",
        threading.Event(),
        manifests_dir=manifests_dir,
    )
    _join(thread)

    # THEN non-install entries and the symlink target remain untouched
    for name in (".manifest", "depot.keys", ".latest-manifest", "notes", "link"):
        assert (manifests_dir / name).exists() or (manifests_dir / name).is_symlink()
    assert (outside / "keep").read_text() == "keep"
    assert not (manifests_dir / "100").exists()


def test_symlinked_prune_directory_is_not_followed(tmp_path: Path) -> None:
    # GIVEN `.prune` is a symlink to an outside directory
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    _install(manifests_dir, "200")
    _install(manifests_dir, "300")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (manifests_dir / manifest_retention.PRUNE_DIR_NAME).symlink_to(outside, target_is_directory=True)
    _activate(manifests_dir, "300")

    # WHEN retaining after preparation of Manifest 300
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "300",
        threading.Event(),
        manifests_dir=manifests_dir,
    )

    # THEN staging is skipped and the target is untouched
    assert thread is None
    assert (manifests_dir / "100").is_dir()
    assert (outside / "keep").read_text() == "keep"


def test_cleanup_removes_staged_data_without_following_symlinks(tmp_path: Path) -> None:
    # GIVEN staged data and a symlink under `.prune`
    manifests_dir = tmp_path / "manifests"
    prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
    prune_dir.mkdir(parents=True)
    (prune_dir / "100").mkdir()
    (prune_dir / "100" / "game.bin").write_bytes(b"game")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (prune_dir / "link").symlink_to(outside, target_is_directory=True)

    # WHEN cleaning the staging directory
    manifest_retention.cleanup_prune_dir(manifests_dir)

    # THEN staged entries are removed, the staging directory remains, and the target survives
    assert prune_dir.is_dir()
    assert not (prune_dir / "100").exists()
    assert not (prune_dir / "link").exists()
    assert (outside / "keep").read_text() == "keep"


def test_cleanup_removes_unreadable_staged_directory(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permission bits")

    # GIVEN a staged directory without read or execute permission
    manifests_dir = tmp_path / "manifests"
    prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
    prune_dir.mkdir(parents=True)
    staged = prune_dir / "100"
    staged.mkdir()
    (staged / "game.bin").write_bytes(b"game")
    staged.chmod(0o000)

    # WHEN cleaning the staging directory
    manifest_retention.cleanup_prune_dir(manifests_dir)

    # THEN the unreadable subtree is removed
    assert prune_dir.is_dir()
    assert not staged.exists()


def test_cleanup_does_not_chmod_symlink_target(tmp_path: Path) -> None:
    # GIVEN a read-only staged directory containing a symlink to a read-only outside directory
    manifests_dir = tmp_path / "manifests"
    prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
    prune_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    outside.chmod(0o500)
    original_mode = outside.stat().st_mode & 0o7777
    staged = prune_dir / "100"
    staged.mkdir()
    (staged / "link").symlink_to(outside, target_is_directory=True)
    staged.chmod(0o555)

    # WHEN cleaning the staging directory
    manifest_retention.cleanup_prune_dir(manifests_dir)

    # THEN the link is removed without changing its target
    assert not staged.exists()
    assert outside.stat().st_mode & 0o7777 == original_mode
    assert (outside / "keep").read_text() == "keep"
    outside.chmod(0o700)


def test_cleanup_waits_for_background_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN a background deletion blocked inside rmtree
    manifests_dir = tmp_path / "manifests"
    prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
    prune_dir.mkdir(parents=True)
    staged = prune_dir / "100"
    staged.mkdir()
    (staged / "game.bin").write_bytes(b"game")
    started = threading.Event()
    release = threading.Event()
    real_rmtree = manifest_retention.shutil.rmtree

    def blocking_rmtree(path: Path) -> None:
        started.set()
        assert release.wait(timeout=5)
        real_rmtree(path)

    monkeypatch.setattr(manifest_retention.shutil, "rmtree", blocking_rmtree)
    thread = manifest_retention.delete_prune_contents_in_background(manifests_dir, threading.Event())
    assert thread is not None
    assert started.wait(timeout=5)

    # WHEN cleanup runs while the background deletion is still in progress
    cleanup_thread = threading.Thread(target=manifest_retention.cleanup_prune_dir, args=(manifests_dir,))
    cleanup_thread.start()
    cleanup_thread.join(timeout=0.2)

    # THEN cleanup waits for the in-flight deletion before returning
    assert cleanup_thread.is_alive()
    release.set()
    _join(thread)
    cleanup_thread.join(timeout=5)
    assert not cleanup_thread.is_alive()
    assert not staged.exists()


def test_stale_prune_collision_is_reclaimed(tmp_path: Path) -> None:
    # GIVEN a live install with a stale staged copy under the same Manifest ID
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    _install(manifests_dir, "200")
    _install(manifests_dir, "300")
    _activate(manifests_dir, "300")
    prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
    prune_dir.mkdir()
    stale = prune_dir / "100"
    stale.mkdir()
    (stale / "old.bin").write_bytes(b"stale")

    # WHEN retaining after preparation of Manifest 300
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "300",
        threading.Event(),
        manifests_dir=manifests_dir,
    )
    _join(thread)

    # THEN the stale copy is replaced and the live install is reclaimed
    assert not (manifests_dir / "100").exists()
    assert not (prune_dir / "100").exists()


def test_read_only_install_tree_is_deleted(tmp_path: Path) -> None:
    # GIVEN an old install with read-only directories
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    old = _install(manifests_dir, "100")
    nested = old / "nested"
    nested.mkdir()
    (nested / "game.bin").write_bytes(b"game")
    nested.chmod(0o500)
    old.chmod(0o500)
    _install(manifests_dir, "200")
    _install(manifests_dir, "300")
    _activate(manifests_dir, "300")

    # WHEN retaining after preparation of Manifest 300
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "300",
        threading.Event(),
        manifests_dir=manifests_dir,
    )
    _join(thread)

    # THEN the read-only install is deleted
    assert not old.exists()


def test_failed_stage_rename_preserves_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN a read-only candidate whose staging rename fails
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    old = _install(manifests_dir, "100", mtime_ns=1_000)
    _install(manifests_dir, "200", mtime_ns=2_000)
    _install(manifests_dir, "300")
    _activate(manifests_dir, "300")
    old.chmod(0o500)
    real_rename = Path.rename

    def fail_rename(self: Path, target: Path) -> Path:
        if self == old:
            msg = "rename failed"
            raise OSError(msg)
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_rename)

    # WHEN retaining after preparation of Manifest 300
    thread = manifest_retention.retain_after_start(
        _settings(version="latest"),
        "300",
        threading.Event(),
        manifests_dir=manifests_dir,
    )

    # THEN the install stays untouched and keeps its read-only mode
    assert thread is None
    assert old.is_dir()
    assert old.stat().st_mode & 0o777 == 0o500
    assert not (manifests_dir / manifest_retention.PRUNE_DIR_NAME / "100").exists()
    old.chmod(0o700)


def test_reclamation_keeps_requested_active_previous_and_game_tree(tmp_path: Path) -> None:
    # GIVEN a requested Manifest, recorded Active/Previous, a Game tree install, and an old install
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    for manifest_id in ("100", "200", "300", "350", "400"):
        _install(manifests_dir, manifest_id)
    _activate(manifests_dir, "200", "300")
    game_tree = tmp_path / "gameserver"
    game_tree.mkdir()
    (game_tree / "enshrouded_server.exe").symlink_to(manifests_dir / "350" / "game.bin")

    # WHEN reclaiming before downloading Manifest 400
    staged = manifest_retention.reclaim_for_download(
        manifests_dir,
        requested_id="400",
        game_tree_dir=game_tree,
    )

    # THEN only the install outside the reclamation keep set is deleted
    assert [path.name for path in staged] == ["100"]
    assert not (manifests_dir / "100").exists()
    for manifest_id in ("200", "300", "350", "400"):
        assert (manifests_dir / manifest_id).is_dir()


def test_reclamation_keeps_every_linked_game_tree_install(tmp_path: Path) -> None:
    # GIVEN a Game tree linking two Manifest installs and an old install
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    for manifest_id in ("100", "200", "350", "360", "400"):
        _install(manifests_dir, manifest_id)
    _activate(manifests_dir, "200", "400")
    game_tree = tmp_path / "gameserver"
    game_tree.mkdir()
    (game_tree / "one.exe").symlink_to(manifests_dir / "350" / "game.bin")
    (game_tree / "two.exe").symlink_to(manifests_dir / "360" / "game.bin")

    # WHEN reclaiming before downloading Manifest 400
    staged = manifest_retention.reclaim_for_download(
        manifests_dir,
        requested_id="400",
        game_tree_dir=game_tree,
    )

    # THEN both linked installs remain and only the old install is reclaimed
    assert [path.name for path in staged] == ["100"]
    assert not (manifests_dir / "100").exists()
    for manifest_id in ("200", "350", "360", "400"):
        assert (manifests_dir / manifest_id).is_dir()


def test_reclamation_fallback_excludes_requested_active_and_game_tree(tmp_path: Path) -> None:
    # GIVEN no recorded previous and a recent install backing the Game tree
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100", mtime_ns=1_000)
    _install(manifests_dir, "200", mtime_ns=2_000)
    _install(manifests_dir, "300", mtime_ns=3_000)
    _install(manifests_dir, "350", mtime_ns=4_000)
    _install(manifests_dir, "400", mtime_ns=5_000)
    _activate(manifests_dir, "300")
    game_tree = tmp_path / "gameserver"
    game_tree.mkdir()
    (game_tree / "enshrouded_server.exe").symlink_to(manifests_dir / "350" / "game.bin")

    # WHEN reclaiming before downloading Manifest 400
    manifest_retention.reclaim_for_download(manifests_dir, requested_id="400", game_tree_dir=game_tree)

    # THEN the fallback is the newest install outside the keep set
    assert (manifests_dir / "200").is_dir()
    assert not (manifests_dir / "100").exists()
    for manifest_id in ("300", "350", "400"):
        assert (manifests_dir / manifest_id).is_dir()


def test_pinned_and_disabled_deployments_keep_every_install(tmp_path: Path) -> None:
    # GIVEN an older complete install and a pinned or pruning-disabled deployment
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    _install(manifests_dir, "300")

    # WHEN retaining after each start
    _join(
        manifest_retention.retain_after_start(
            _settings(version="300"),
            "300",
            threading.Event(),
            manifests_dir=manifests_dir,
        )
    )
    _join(
        manifest_retention.retain_after_start(
            _settings(version="latest", manifest_prune_enabled=False),
            "300",
            threading.Event(),
            manifests_dir=manifests_dir,
        )
    )

    # THEN neither deployment deletes the older install
    assert (manifests_dir / "100").is_dir()
    assert (manifests_dir / "300").is_dir()


def test_cleanup_runs_when_pruning_disabled(tmp_path: Path) -> None:
    # GIVEN staged prune data and a pruning-disabled deployment
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    _install(manifests_dir, "100")
    _install(manifests_dir, "300")
    prune_dir = manifests_dir / manifest_retention.PRUNE_DIR_NAME
    prune_dir.mkdir()
    (prune_dir / "999").mkdir()
    (prune_dir / "999" / "game.bin").write_bytes(b"stale")
    _activate(manifests_dir, "300")

    # WHEN cleaning before a pruning-disabled start
    manifest_retention.cleanup_prune_dir(manifests_dir)
    _join(
        manifest_retention.retain_after_start(
            _settings(version="latest", manifest_prune_enabled=False),
            "300",
            threading.Event(),
            manifests_dir=manifests_dir,
        )
    )

    # THEN staged data is removed but installs remain
    assert prune_dir.is_dir()
    assert not (prune_dir / "999").exists()
    assert (manifests_dir / "100").is_dir()
    assert (manifests_dir / "300").is_dir()


@pytest.mark.parametrize(("version", "expected"), [("latest", True), ("", True), ("123", False), ("build:123", False)])
def test_latest_tracking_classification(version: str, expected: bool) -> None:
    # GIVEN a Version spec
    # WHEN classifying it
    # THEN only latest, empty, and unset values are latest-tracking
    assert is_latest_tracking(version) is expected
