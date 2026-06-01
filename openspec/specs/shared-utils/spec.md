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

### Requirement: Shared boolean env var parser

The system SHALL provide a `is_truthy(env_var: str, default: bool = True) -> bool` function in `enshctl.utils` that parses boolean-like environment variables (`1/true/on/yes` → True, `0/false/off/no` → False).

#### Scenario: Truthy values

- **WHEN** `is_truthy("MY_VAR")` is called and `MY_VAR=true`
- **THEN** it SHALL return `True`

#### Scenario: Falsy values

- **WHEN** `is_truthy("MY_VAR")` is called and `MY_VAR=false`
- **THEN** it SHALL return `False`

#### Scenario: Default when unset

- **WHEN** `is_truthy("MY_VAR", default=False)` is called and `MY_VAR` is not set
- **THEN** it SHALL return `False`

### Requirement: Shared UID/GID resolver

The system SHALL provide a `get_uid_gid(settings: AppSettings) -> tuple[int, int]` function in `enshctl.utils` that returns the configured UID and GID.

#### Scenario: Returns configured values

- **WHEN** `get_uid_gid(settings)` is called with `settings.puid=1001, settings.pgid=1002`
- **THEN** it SHALL return `(1001, 1002)`
