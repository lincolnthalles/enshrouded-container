## Purpose

Shared formatting and parsing helpers used across enshctl modules.

## Requirements

### Requirement: Unified human-readable size formatting

Byte counts SHALL be formatted as human-readable strings (B, KB, MB, GB, TB) through a single shared helper. All modules SHALL use it instead of implementing their own formatting.

#### Scenario: Format bytes

- **WHEN** 1536 bytes are formatted
- **THEN** the result SHALL be `"1.5 KB"`

#### Scenario: Format gigabytes

- **WHEN** 2 GiB are formatted
- **THEN** the result SHALL be `"2.0 GB"`

### Requirement: Boolean settings parsing behavior

Boolean settings SHALL parse `1/true/on/yes` (case-insensitive) as True and `0/false/off/no` as False. Unset or empty values SHALL resolve to the setting's documented default. Unrecognized non-empty values SHALL resolve to the setting's documented default rather than silently disabling the feature.

#### Scenario: Truthy values

- **WHEN** a live-backup setting is `true` (or `1`, `on`, `yes`)
- **THEN** the live-backup setting SHALL resolve to True

#### Scenario: Falsy values

- **WHEN** a live-backup setting is `false` (or `0`, `off`, `no`)
- **THEN** the live-backup setting SHALL resolve to False

#### Scenario: Unrecognized value falls back to default

- **WHEN** a cold-backup setting is set to an unrecognized value such as `enabled`
- **THEN** the cold-backup setting SHALL resolve to its documented default (True)
