## Purpose

Non-mutating generation of the Generated config from the Base config plus environment overrides.

## Requirements

### Requirement: Non-mutating config merge

Config generation SHALL return a new dictionary without mutating the Base config. Environment overrides SHALL be merged over the Base config; game-written fields SHALL survive when no override targets them.

#### Scenario: Base config preserved after merge

- **WHEN** config generation runs with a Base config loaded from file
- **THEN** the original Base config SHALL NOT be modified by the merge operation

#### Scenario: Runtime config survives regeneration

- **WHEN** the persisted config contains game-written fields and the container restarts with no overrides targeting those fields
- **THEN** the Generated config SHALL retain the game-written values

### Requirement: Base config source

The Base config SHALL be the persisted config file when present, else the Example config from the Manifest install, else empty with a warning.

#### Scenario: Persisted config is used as base

- **WHEN** the persisted config file exists
- **THEN** its contents SHALL be used as the Base config

#### Scenario: No persisted config falls back to example

- **WHEN** no persisted config file exists and the Example config is present in the Manifest install
- **THEN** the Example config SHALL be used as the Base config

#### Scenario: No base config warns and starts empty

- **WHEN** neither the persisted config nor the Example config exists
- **THEN** a warning SHALL be logged, the Base config SHALL be empty, and save/log defaults SHALL still apply

### Requirement: Env var to Generated config conversion

Environment variables with the `ENSHROUDED_` prefix (case-insensitive for the prefix) SHALL be converted to nested JSON keys and merged into the Base config. Nesting SHALL use double underscores (`__`) to separate path segments; single underscores (`_`) within a segment SHALL become lowerCamelCase. Segments that are pure numbers SHALL address array positions; name-keyed groups SHALL resolve to arrays carrying each entry's name when the Base config holds a list at that key or provides no hint, and SHALL recurse as dictionaries when the Base config holds a dictionary there. Each segment SHALL be lowercased before camel-casing, so acronyms are not preserved. Variables without the prefix, or with an empty remainder, SHALL be ignored.

#### Scenario: Simple string setting

- **WHEN** `ENSHROUDED_NAME` names a server
- **THEN** the Generated config SHALL contain that name string

#### Scenario: Nested setting with double-underscore segments

- **WHEN** an env var targets a nested player-health key via `__`
- **THEN** the Generated config SHALL contain the nested numeric value

#### Scenario: Boolean value detection

- **WHEN** an env var targets a nested boolean key with `true`
- **THEN** the Generated config SHALL contain the boolean (not string)

#### Scenario: Integer value detection

- **WHEN** an env var targets a slot-count key with digits
- **THEN** the Generated config SHALL contain the integer (not string)

#### Scenario: Float value detection

- **WHEN** an env var targets a day-time factor key with a decimal
- **THEN** the Generated config SHALL contain the float

#### Scenario: JSON array value

- **WHEN** an env var targets a key with a JSON array value
- **THEN** the Generated config SHALL contain the parsed array

#### Scenario: Env var without prefix is ignored

- **WHEN** an env var without the `ENSHROUDED_` prefix is set
- **THEN** the env var SHALL NOT affect the Generated config

#### Scenario: Config is schema-agnostic

- **WHEN** an env var targets a key the current game schema does not define
- **THEN** the Generated config SHALL contain the key regardless

#### Scenario: Single underscore stays within one segment

- **WHEN** an env var uses single underscores with no `__`
- **THEN** the Generated config SHALL contain a single flat camelCase key and SHALL NOT nest

#### Scenario: Array index segment

- **WHEN** an env var uses a numeric segment to address a group position
- **THEN** the Generated config SHALL contain an array with the value at that position

#### Scenario: Name-keyed group resolves to named array

- **WHEN** env vars use group names as keys for a group setting and the Base config holds a list there or provides no hint
- **THEN** the Generated config SHALL contain an array of objects each carrying its group name

#### Scenario: Acronyms lowercased

- **WHEN** the key after prefix removal is an acronym such as `IP`
- **THEN** the JSON key SHALL be fully lowercased

#### Scenario: Lowercase input

- **WHEN** the key is already lowercase after prefix removal
- **THEN** the JSON key SHALL remain lowercase

### Requirement: Generated config placement and ownership

The Generated config SHALL be written to the config directory after applying all env var overrides. The persisted config file SHALL be owned by the configured `PUID`/`PGID` (see `shared-config` for where ownership values originate).

#### Scenario: Config is written to config dir

- **WHEN** config generation completes
- **THEN** the persisted config file SHALL exist with the merged configuration

#### Scenario: Config overrides are applied to base

- **WHEN** a Base config names a server and an env var overrides that name
- **THEN** the output SHALL contain the overridden name

#### Scenario: Config file owned by configured user

- **WHEN** config generation completes with ownership configured
- **THEN** the persisted config file SHALL be owned by the configured user and group

### Requirement: Generated query endpoint consumption

A2S and wake resolution SHALL read `ip` and `queryPort` from the Generated config without changing
generation. `queryPort` SHALL be an integer in `1..65535`; booleans, strings, floats, and
out-of-range values SHALL return no endpoint with a warning. `0.0.0.0` and an empty `ip` SHALL map
to `127.0.0.1`; `::` and `::0` SHALL map to `::1`; a specific valid address SHALL be used as-is.
An invalid address SHALL fall back to `127.0.0.1` with a warning.

#### Scenario: Wildcard bind maps to loopback

- **WHEN** the Generated config has `"ip": "0.0.0.0"` and a valid query port
- **THEN** A2S SHALL use `127.0.0.1` and that port
- **AND** wake SHALL match UDP traffic by destination port on every interface

#### Scenario: Invalid port has no endpoint

- **WHEN** `queryPort` is a boolean, string, float, or outside `1..65535`
- **THEN** no query endpoint SHALL be returned
- **AND** a warning SHALL name the discarded value

#### Scenario: Missing or unreadable config has no endpoint

- **WHEN** the Generated config is missing, unreadable, or not a JSON object
- **THEN** no query endpoint SHALL be returned
- **AND** a warning SHALL be logged

#### Scenario: Generation does not consume the endpoint

- **WHEN** config generation runs
- **THEN** `ip` and `queryPort` SHALL remain driven only by the Base config and environment
  overrides
- **AND** query-endpoint resolution SHALL NOT mutate the Generated config
