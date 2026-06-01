## Requirements

### Requirement: Centralized path constants

The system SHALL define all filesystem path constants (`SAVE_DIR`, `MANIFESTS_DIR`, `CONFIG_DIR`, `MOUNT_POINT`, `WINE_PREFIX`, `BACKUP_BASE_DIR`) in a single `settings.py` module. All other modules SHALL import paths from this module rather than defining their own.

#### Scenario: Single source of truth for SAVE_DIR

- **WHEN** any module needs the saves directory path
- **THEN** it SHALL import `SAVE_DIR` from `enshctl.settings` rather than defining `Path("/data/saves")` locally

#### Scenario: No duplicated path definitions

- **WHEN** the codebase is scanned for `Path("/data/manifests")`
- **THEN** it SHALL appear only in `enshctl/settings.py`

### Requirement: Typed settings dataclass

The system SHALL provide a frozen dataclass `AppSettings` that holds all environment-variable-derived configuration. The dataclass SHALL be populated by a `load_settings()` function that reads `os.environ` once. All modules SHALL accept settings via function parameters or import from the settings module rather than calling `os.environ.get()` directly.

#### Scenario: Settings loaded once at startup

- **WHEN** the `start` command runs
- **THEN** `load_settings()` SHALL be called once and the resulting `AppSettings` instance SHALL be passed to subsystems

#### Scenario: Settings are frozen

- **WHEN** an `AppSettings` instance is created
- **THEN** attempting to modify an attribute SHALL raise `FrozenInstanceError`

#### Scenario: Testable without env var manipulation

- **WHEN** a test needs custom settings
- **THEN** it SHALL construct an `AppSettings` instance directly with test values, without modifying `os.environ`

### Requirement: PUID/PGID resolved once

The system SHALL read `PUID` and `PGID` environment variables once in `load_settings()` and expose them as `AppSettings.puid` and `AppSettings.pgid`. All modules SHALL use the settings object instead of reading these env vars independently.

#### Scenario: Consistent UID/GID across modules

- **WHEN** `PUID=1001` is set
- **THEN** all modules SHALL use uid 1001 from the settings object, not from independent `os.environ.get("PUID")` calls
