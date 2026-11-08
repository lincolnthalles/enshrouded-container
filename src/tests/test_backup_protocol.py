"""Tests for the shared Backup trigger and request contract."""

import argparse
from argparse import Namespace
from pathlib import Path
from typing import cast

import pytest
from enshctl.backup.category import Category
from enshctl.backup_protocol import BackupRequest, Trigger, add_arguments


def test_for_trigger_maps_scheduled_live() -> None:
    # GIVEN a scheduler trigger
    request = BackupRequest.for_trigger(Trigger.SCHEDULED)

    # THEN it maps to a non-detached live backup
    assert request == BackupRequest(category=Category.LIVE, detach=False)


def test_for_trigger_maps_shutdown_cold() -> None:
    # GIVEN a shutdown trigger with a lock wait
    request = BackupRequest.for_trigger(Trigger.SHUTDOWN, wait_seconds=5)

    # THEN it maps to a detached cold backup carrying the wait
    assert request == BackupRequest(category=Category.COLD, wait_seconds=5, detach=True)


def test_for_trigger_maps_update_cold() -> None:
    # GIVEN an update restart trigger with a lock wait
    request = BackupRequest.for_trigger(Trigger.UPDATE, wait_seconds=5)

    # THEN it maps to a detached cold backup carrying the wait
    assert request == BackupRequest(category=Category.COLD, wait_seconds=5, detach=True)


def test_for_trigger_maps_crash_emergency() -> None:
    # GIVEN a crash trigger
    request = BackupRequest.for_trigger(Trigger.CRASH)

    # THEN it maps to a detached emergency backup
    assert request == BackupRequest(category=Category.EMERGENCY, detach=True)


def test_manual_trigger_requires_explicit_category() -> None:
    # GIVEN the manual trigger
    # WHEN building a request without a Category
    # THEN it fails instead of guessing
    with pytest.raises(ValueError, match="explicitly"):
        BackupRequest.for_trigger(Trigger.MANUAL)


@pytest.mark.parametrize(
    ("category", "flag"),
    [
        (Category.LIVE, []),
        (Category.COLD, ["--cold"]),
        (Category.EMERGENCY, ["--emergency"]),
    ],
)
def test_backup_request_argv_round_trip(category: Category, flag: list[str]) -> None:
    # GIVEN a typed Backup request
    request = BackupRequest(category=category, wait_seconds=7)
    # WHEN it crosses the child-process seam
    assert request.to_argv() == [*flag, "--wait", "7"]
    args = Namespace(
        cold=category is Category.COLD,
        emergency=category is Category.EMERGENCY,
        wait=7,
        format=None,
        level=None,
        saves_dir=None,
    )
    # THEN the child reconstructs the same request
    assert BackupRequest.from_argv(args) == request


def test_backup_request_argv_carries_compression_options() -> None:
    # GIVEN a request with per-invocation compression options
    request = BackupRequest(category=Category.COLD, fmt="gzip", level=5)

    # WHEN it crosses the child-process seam
    assert request.to_argv() == ["--cold", "--format", "gzip", "--level", "5"]
    args = Namespace(cold=True, emergency=False, wait=0, format="gzip", level=5, saves_dir=None)

    # THEN the child reconstructs the same request
    assert BackupRequest.from_argv(args) == request


def test_backup_request_argv_carries_resolved_save_dir() -> None:
    # GIVEN a request carrying the parent's resolved Save directory
    saves = Path("/mnt/nfs/saves")
    request = BackupRequest(category=Category.LIVE, saves_dir=saves)

    # WHEN it crosses the child-process seam
    assert request.to_argv() == ["--saves-dir", str(saves)]
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args(["--saves-dir", str(saves)])

    # THEN the child parser reconstructs the same request
    assert BackupRequest.from_argv(args) == request


def test_saves_dir_flag_is_hidden_from_help() -> None:
    # GIVEN the backup child parser
    parser = argparse.ArgumentParser()
    add_arguments(parser)

    # WHEN rendering help
    help_text = parser.format_help()

    # THEN the internal parent-to-child flag is not advertised
    assert "--saves-dir" not in help_text


def test_backup_request_rejects_unknown_category() -> None:
    # GIVEN an unknown Category string at the protocol boundary
    # WHEN constructing a request
    # THEN it fails before reaching argv
    with pytest.raises(ValueError, match="warm"):
        BackupRequest(category=cast("Category", "warm"))


def test_parser_rejects_both_cold_and_emergency() -> None:
    # GIVEN the backup child parser
    parser = argparse.ArgumentParser()
    add_arguments(parser)

    # WHEN both Category flags are supplied
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--cold", "--emergency"])

    # THEN argparse rejects the ambiguous request
    assert exc_info.value.code == 2


def test_parser_lowercases_format_and_rejects_unknown() -> None:
    # GIVEN the backup child parser
    parser = argparse.ArgumentParser()
    add_arguments(parser)

    # WHEN an uppercase format is supplied
    args = parser.parse_args(["--format", "ZSTD"])

    # THEN it is accepted in lowercase
    assert args.format == "zstd"

    # AND an unrecognized format is rejected by argparse
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--format", "lz4"])
    assert exc_info.value.code == 2
