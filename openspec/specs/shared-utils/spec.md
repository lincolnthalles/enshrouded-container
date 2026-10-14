## Purpose

Shared formatting and parsing helpers used across enshctl modules.

## Requirements

### Requirement: Unified human-readable size formatting

The system SHALL provide a single `human_size(size_bytes: int | float) -> str` function in `enshctl.utils` that formats byte counts as human-readable strings (B, KB, MB, GB, TB). All modules SHALL use this function instead of implementing their own formatting.

#### Scenario: Format bytes

- **WHEN** `human_size(1536)` is called
- **THEN** it SHALL return `"1.5 KB"`

#### Scenario: Format gigabytes

- **WHEN** `human_size(2 * 1024**3)` is called
- **THEN** it SHALL return `"2.0 GB"`

#### Scenario: Single implementation used everywhere

- **WHEN** the codebase is scanned for human-readable size formatting
- **THEN** `human_size` SHALL be defined only in `enshctl/utils.py`

### Requirement: Boolean settings parsing behavior

Boolean settings SHALL parse `1/true/on/yes` (case-insensitive) as True and `0/false/off/no` as False. Unset or empty values SHALL resolve to the setting's documented default. Unrecognized non-empty values SHALL resolve to the setting's documented default rather than silently disabling the feature.

#### Scenario: Truthy values

- **WHEN** `BACKUP_LIVE=true` (or `1`, `on`, `yes`)
- **THEN** the live-backup setting SHALL resolve to True

#### Scenario: Falsy values

- **WHEN** `BACKUP_LIVE=false` (or `0`, `off`, `no`)
- **THEN** the live-backup setting SHALL resolve to False

#### Scenario: Unrecognized value falls back to default

- **WHEN** `BACKUP_COLD` is set to an unrecognized value such as `enabled`
- **THEN** the cold-backup setting SHALL resolve to its documented default (True)

### Requirement: UID/GID resolved once

The system SHALL read `PUID` and `PGID` environment variables once per `load_settings()` call and expose them as `AppSettings.puid` and `AppSettings.pgid`. All modules SHALL use these fields directly instead of reading the env vars independently.

#### Scenario: Consistent UID/GID across modules

- **WHEN** `PUID=1001` is set
- **THEN** all modules SHALL use uid 1001 from the settings object, not from independent `os.environ.get("PUID")` calls
