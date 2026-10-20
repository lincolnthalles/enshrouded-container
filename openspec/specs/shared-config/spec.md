## Purpose

Centralized configuration for the enshctl orchestrator: filesystem path constants and environment-derived settings.

## Requirements

### Requirement: Centralized path constants

The system SHALL define all filesystem path constants (`SAVE_DIR`, `MANIFESTS_DIR`, `CONFIG_DIR`, `MOUNT_POINT`, `WINE_PREFIX`, `BACKUP_BASE_DIR`) in a single `paths.py` module. All other modules SHALL import paths from this module rather than defining their own.

#### Scenario: Single source of truth for SAVE_DIR

- **WHEN** any module needs the saves directory path
- **THEN** it SHALL import `SAVE_DIR` from `enshctl.paths` rather than defining `Path("/data/saves")` locally

#### Scenario: No duplicated path definitions

- **WHEN** the codebase is scanned for `Path("/data/manifests")`
- **THEN** it SHALL appear only in `enshctl/paths.py`

### Requirement: Typed settings dataclass

The system SHALL provide a frozen dataclass `AppSettings` that holds all environment-variable-derived configuration. The dataclass SHALL be populated by a `load_settings()` function that reads `os.environ` once per call. All modules SHALL accept settings via function parameters or import from the settings module rather than calling `os.environ.get()` directly.

#### Scenario: Settings loaded once at startup

- **WHEN** the `start` command runs
- **THEN** `load_settings()` SHALL be called once per process entrypoint and the resulting `AppSettings` instance SHALL be passed to subsystems; the backup subprocess SHALL reload settings from its inherited environment

#### Scenario: Settings are frozen

- **WHEN** an `AppSettings` instance is created
- **THEN** attempting to modify an attribute SHALL raise `FrozenInstanceError`

#### Scenario: Testable without env var manipulation

- **WHEN** a test needs custom settings
- **THEN** it SHALL construct an `AppSettings` instance directly with test values, without modifying `os.environ`

### Requirement: Settings loaded once per process entrypoint

Each process entrypoint SHALL call `load_settings()` once and pass the resulting `AppSettings` instance to subsystems via function parameters. Across a subprocess seam, the child process SHALL reload settings from its inherited environment rather than receiving them over IPC. The parent SHALL forward the settings-bearing environment keys (all `BACKUP_*`, `PUID`, `PGID`, plus the base allowlist) so the child observes the same configured values.

#### Scenario: Start command loads once

- **WHEN** the `start` command runs
- **THEN** `load_settings()` SHALL be called once in `start.run()` and the resulting `AppSettings` instance SHALL be passed to subsystems

#### Scenario: Reload across the backup subprocess seam

- **WHEN** `start` spawns `enshctl backup` as a subprocess
- **THEN** the child SHALL call `load_settings()` on its inherited environment, observing the same values the parent configured

### Requirement: PUID/PGID resolved once

The system SHALL read `PUID` and `PGID` environment variables once in `load_settings()` and expose them as `AppSettings.puid` and `AppSettings.pgid`. All modules SHALL use the settings object instead of reading these env vars independently.

#### Scenario: Consistent UID/GID across modules

- **WHEN** `PUID=1001` is set
- **THEN** all modules SHALL use uid 1001 from the settings object, not from independent `os.environ.get("PUID")` calls
