"""Tests for the settings seam."""

from dataclasses import FrozenInstanceError, fields, replace
from unittest.mock import patch

import pytest
from enshctl.settings import AppSettings, backup_child_env, load_settings


def test_load_settings_without_source_reads_process_environment() -> None:
    # GIVEN a process environment carrying a settings value
    with patch("enshctl.settings.environ", {"PUID": "1234"}):
        # WHEN loading settings without an explicit mapping
        settings = load_settings()
    # THEN the ambient value is used
    assert settings == replace(AppSettings(), puid=1234)


def test_load_settings_with_explicit_source_ignores_process_environment() -> None:
    # GIVEN ambient settings that differ from the supplied mapping
    with patch("enshctl.settings.environ", {"PUID": "9999", "BACKUP_DIR": "/ambient/backups"}):
        # WHEN loading from an explicit mapping
        settings = load_settings({"PUID": "1234"})
    # THEN only the supplied mapping contributes
    assert settings == replace(AppSettings(), puid=1234)


def test_load_settings_with_empty_source_yields_defaults() -> None:
    # GIVEN an empty explicit mapping
    # WHEN loading settings
    # THEN the documented defaults apply
    assert load_settings({}) == AppSettings()


def test_direct_construction_ignores_process_environment() -> None:
    # GIVEN ambient settings that must not leak into direct construction
    with patch("enshctl.settings.environ", {"PUID": "9999"}):
        # WHEN constructing directly and loading an empty mapping
        # THEN both yield the same documented defaults
        assert AppSettings() == load_settings({})


def test_app_settings_defaults_are_documented_values() -> None:
    # GIVEN direct construction
    # WHEN reading the settings object
    # THEN every default matches the documented contract
    assert AppSettings() == AppSettings(
        puid=1000,
        pgid=1000,
        version="latest",
        force_install=False,
        manifest_prune_enabled=True,
        min_free_space=10 * 1024**3,
        auto_update_enabled=True,
        auto_update_cron="*/60 * * * *",
        auto_update_log_only=False,
        auto_update_download_only_when_empty=False,
        manifesthub_api_token=None,
        manifesthub_api_url=None,
        depot_keys_repo=None,
        steam_username=None,
        steam_password=None,
        backup_dir="/data/backups",
        backup_format="zstd",
        backup_level=None,
        backup_cron="*/60 * * * *",
        backup_min_free_warn=2 * 1024**3,
        backup_min_free_stop=1 * 1024**3,
        backup_live=True,
        backup_cold=True,
        backup_emergency=True,
        log_tail=False,
        resource_poll_interval=60,
        player_log=True,
        player_poll_interval=60,
        auto_pause_enabled=False,
        auto_pause_idle_timeout=300,
        auto_pause_wake_filter="any",
        shutdown_timeout=60,
        shutdown_backup_wait=120,
        orchestrator_log_file="",
        orchestrator_log_level="WARNING",
        winearch="win64",
        winedebug="fixme-all",
        winedlloverrides=None,
        home="/home/steam",
        tz="UTC",
        persist_files=(),
        backup_keep_last=24,
        backup_keep_hourly=0,
        backup_keep_daily=0,
        backup_keep_weekly=0,
        backup_keep_monthly=0,
        backup_keep_yearly=0,
    )


def test_load_settings_parses_every_declared_key() -> None:
    # GIVEN one value for every environment-derived setting
    source = {
        "PUID": "1001",
        "PGID": "1002",
        "VERSION": " Build:123 ",
        "FORCE_INSTALL": "yes",
        "MANIFEST_PRUNE_ENABLED": "off",
        "INSTALL_MIN_FREE_SPACE": "111",
        "AUTO_UPDATE_ENABLED": "false",
        "AUTO_UPDATE_CRON": " */5 * * * * ",
        "AUTO_UPDATE_LOG_ONLY": "true",
        "AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY": "true",
        "MANIFESTHUB_API_TOKEN": " token ",
        "MANIFESTHUB_API_URL": " https://mirror.example.com/ ",
        "DEPOT_KEYS_REPO": " repo ",
        "STEAM_USERNAME": " user ",
        "STEAM_PASSWORD": " pass ",
        "BACKUP_DIR": " /mnt/backups ",
        "BACKUP_FORMAT": " gzip ",
        "BACKUP_LEVEL": "7",
        "BACKUP_CRON": " */5 * * * * ",
        "BACKUP_MIN_FREE_SPACE_WARN": "222",
        "BACKUP_MIN_FREE_SPACE_STOP": "333",
        "BACKUP_LIVE": "false",
        "BACKUP_COLD": "off",
        "BACKUP_EMERGENCY": "0",
        "LOG_TAIL": "true",
        "RESOURCE_POLL_INTERVAL": "5",
        "PLAYER_LOG": "false",
        "PLAYER_POLL_INTERVAL": "7",
        "AUTO_PAUSE_ENABLED": "true",
        "AUTO_PAUSE_IDLE_TIMEOUT": "45",
        "AUTO_PAUSE_WAKE_FILTER": " Ignore-A2S ",
        "SHUTDOWN_TIMEOUT": "-1",
        "SHUTDOWN_BACKUP_WAIT": "10",
        "ORCHESTRATOR_LOG_FILE": " true ",
        "ORCHESTRATOR_LOG_LEVEL": " debug ",
        "WINEARCH": " win32 ",
        "WINEDEBUG": " -all ",
        "WINEDLLOVERRIDES": "",
        "HOME": " /home/x ",
        "TZ": " Europe/Berlin ",
        "PERSIST_FILES": " a, b, , c ",
        "BACKUP_KEEP_LAST": "3",
        "BACKUP_KEEP_HOURLY": "4",
        "BACKUP_KEEP_DAILY": "5",
        "BACKUP_KEEP_WEEKLY": "6",
        "BACKUP_KEEP_MONTHLY": "7",
        "BACKUP_KEEP_YEARLY": "8",
    }
    # AND the test source covers every declared env key
    assert set(source) == {f.metadata["env_key"] for f in fields(AppSettings)}
    # WHEN loading settings
    settings = load_settings(source)
    # THEN every field carries its parsed value
    assert settings == replace(
        AppSettings(),
        puid=1001,
        pgid=1002,
        version="build:123",
        force_install=True,
        manifest_prune_enabled=False,
        min_free_space=111,
        auto_update_enabled=False,
        auto_update_cron="*/5 * * * *",
        auto_update_log_only=True,
        auto_update_download_only_when_empty=True,
        manifesthub_api_token="token",
        manifesthub_api_url="https://mirror.example.com",
        depot_keys_repo="repo",
        steam_username="user",
        steam_password="pass",
        backup_dir="/mnt/backups",
        backup_format="gzip",
        backup_level=7,
        backup_cron="*/5 * * * *",
        backup_min_free_warn=222,
        backup_min_free_stop=333,
        backup_live=False,
        backup_cold=False,
        backup_emergency=False,
        log_tail=True,
        resource_poll_interval=5,
        player_log=False,
        player_poll_interval=7,
        auto_pause_enabled=True,
        auto_pause_idle_timeout=45,
        auto_pause_wake_filter="ignore-a2s",
        shutdown_timeout=0,
        shutdown_backup_wait=10,
        orchestrator_log_file="true",
        orchestrator_log_level="debug",
        winearch="win32",
        winedebug="-all",
        winedlloverrides="",
        home="/home/x",
        tz="Europe/Berlin",
        persist_files=("a", "b", "c"),
        backup_keep_last=3,
        backup_keep_hourly=4,
        backup_keep_daily=5,
        backup_keep_weekly=6,
        backup_keep_monthly=7,
        backup_keep_yearly=8,
    )


def test_load_settings_preserves_invalid_and_empty_fallbacks() -> None:
    # GIVEN malformed and empty values at the environment boundary
    source = {
        "PUID": "not-a-number",
        "PGID": "",
        "FORCE_INSTALL": "maybe",
        "BACKUP_LEVEL": "",
        "BACKUP_LIVE": "maybe",
        "BACKUP_COLD": "",
        "PLAYER_LOG": "maybe",
        "PLAYER_POLL_INTERVAL": "-30",
        "AUTO_PAUSE_ENABLED": "maybe",
        "AUTO_PAUSE_IDLE_TIMEOUT": "-30",
        "AUTO_PAUSE_WAKE_FILTER": "sometimes",
        "AUTO_UPDATE_ENABLED": "maybe",
        "AUTO_UPDATE_LOG_ONLY": "maybe",
        "AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY": "maybe",
        "SHUTDOWN_TIMEOUT": "-30",
        "MANIFESTHUB_API_TOKEN": "   ",
        "MANIFESTHUB_API_URL": "   ",
        "WINEDLLOVERRIDES": "",
    }
    # WHEN loading settings
    settings = load_settings(source)
    # THEN the existing fallback semantics are preserved
    assert settings == replace(
        AppSettings(),
        player_poll_interval=0,
        auto_pause_idle_timeout=0,
        shutdown_timeout=0,
        winedlloverrides="",
    )


def test_load_settings_falls_back_for_non_integer_poll_interval() -> None:
    # GIVEN a malformed player poll interval
    source = {"PLAYER_POLL_INTERVAL": "often"}

    # WHEN loading settings
    settings = load_settings(source)

    # THEN the documented default applies
    assert settings.player_poll_interval == 60


def test_load_settings_falls_back_for_invalid_wake_filter(caplog: pytest.LogCaptureFixture) -> None:
    # GIVEN an unknown wake filter
    source = {"AUTO_PAUSE_WAKE_FILTER": "sometimes"}

    # WHEN loading settings
    with caplog.at_level("WARNING", logger="enshctl.settings"):
        settings = load_settings(source)

    # THEN any is used and the discarded value is named
    assert settings.auto_pause_wake_filter == "any"
    assert "sometimes" in caplog.text


def test_settings_are_frozen() -> None:
    # GIVEN loaded settings
    settings = load_settings({})
    field_name = "puid"
    # WHEN attempting to modify an attribute
    with pytest.raises(FrozenInstanceError):
        setattr(settings, field_name, 1)
    # THEN the object remains frozen
    assert settings.puid == 1000


def test_backup_child_env_forwards_only_declared_settings_keys() -> None:
    # GIVEN settings-bearing, unknown, and unrelated environment values
    source = {
        "PUID": "1001",
        "PGID": "1002",
        "BACKUP_DIR": "/mnt/backups",
        "BACKUP_KEEP_LAST": "7",
        "BACKUP_CRON": "*/5 * * * *",
        "BACKUP_FUTURE_UNKNOWN": "nope",
        "STEAM_PASSWORD": "s3cret",
        "PLAYER_LOG": "true",
        "PLAYER_POLL_INTERVAL": "5",
        "PATH": "/usr/bin",
    }
    # WHEN selecting the backup child environment
    child_env = backup_child_env(source)
    # THEN only declared settings keys cross the seam
    assert child_env == {
        "PUID": "1001",
        "PGID": "1002",
        "BACKUP_DIR": "/mnt/backups",
        "BACKUP_KEEP_LAST": "7",
        "BACKUP_CRON": "*/5 * * * *",
    }
