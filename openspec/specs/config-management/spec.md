## Purpose

Non-mutating generation of the Generated config from the Base config plus environment overrides, with keys previously set from the environment removed once their variables are gone, except Example values when no persisted config exists.

## Requirements

### Requirement: Non-mutating config merge

Config generation SHALL return a new dictionary without mutating the Base config. Environment overrides SHALL be merged over the Base config; game-written fields SHALL survive when no override targets them and the field is not a tracked env key whose variable has been removed (see Stale env-set key removal), except when the Base config is the Example config (see Env key tracking record).

#### Scenario: Base config preserved after merge

- **WHEN** config generation runs with a Base config loaded from file
- **THEN** the original Base config SHALL NOT be modified by the merge operation

#### Scenario: Runtime config survives regeneration

- **WHEN** the persisted config contains game-written fields that were never set from the environment and the container restarts with no overrides targeting those fields
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

### Requirement: Stale env-set key removal

On each config generation, a tracked env key that the current environment no longer sets SHALL be absent from the Generated config, while every Base config key that was never tracked SHALL be retained through removal. Retention through removal does not alter replacement by a current override, which is governed by Non-mutating config merge (see Non-mutating config merge). When the persisted config is absent so the Example config supplies the Base config, Example values SHALL be retained even for tracked keys (see Env key tracking record). A value set as a JSON object counts as its individual keys, so removal deletes only those keys; a value set as a JSON array counts as a single key holding the whole array, so removal deletes the whole array. A name-keyed group entry counts as its individual keys under its group name, and removal SHALL match the entry by group name, not array position. The name field carried for name-keyed resolution is entry identity and SHALL NOT be tracked; it SHALL be preserved while any non-identity key of the entry survives and removed only with the whole entry. An entry holding only its identity name after a removal is considered emptied for pruning purposes. If a removal directly empties an object or array entry, it SHALL itself be removed, including ancestors directly emptied by that pruning; an entry already empty before the removal SHALL be retained unless its path is itself removed. Every removal SHALL be logged at warning level naming the removed keys.

#### Scenario: Removed env var removes its setting

- **WHEN** a config write records a nested resource-drop factor set from the environment and the container restarts without that variable
- **THEN** the Generated config SHALL NOT contain that factor key
- **AND** a warning log record SHALL name the removed key

#### Scenario: Future key is removed

- **WHEN** a config write records a key the current game schema does not define and the container restarts without its variable
- **THEN** the Generated config SHALL NOT contain that key

#### Scenario: Untracked keys survive removal

- **WHEN** the Base config holds a manually set or game-written key that was never set from the environment and another key is removed as stale
- **THEN** the Generated config SHALL retain the untracked key

#### Scenario: Tracked key loses to removal after a file edit

- **WHEN** a recorded key's value is edited directly in the persisted config and the container restarts without its variable
- **THEN** the Generated config SHALL NOT contain that key

#### Scenario: Sibling keys survive a nested removal

- **WHEN** one recorded key under a settings object is removed as stale and the same object holds other keys from the Base config or the current environment
- **THEN** the Generated config SHALL retain those other keys

#### Scenario: Composite value removes only its own keys

- **WHEN** a variable sets a settings object as a JSON value, that write is recorded, and the container restarts without the variable while the Base config holds another key under the same object
- **THEN** the Generated config SHALL NOT contain the keys the JSON value set
- **AND** the Generated config SHALL retain the other key

#### Scenario: Array value removes wholly

- **WHEN** a variable sets a key as a JSON array value, that write is recorded, and the container restarts without the variable
- **THEN** the Generated config SHALL NOT contain that array key

#### Scenario: Emptied container is pruned

- **WHEN** removing stale keys directly empties an object or an array entry
- **THEN** the Generated config SHALL NOT contain that empty object or entry

#### Scenario: Pre-existing empty container survives

- **WHEN** the Base config holds an object or array entry already empty and not tracked, and another key is removed as stale
- **THEN** the Generated config SHALL retain that pre-existing empty container

#### Scenario: Name-keyed group removal

- **WHEN** env vars set two tracked name-keyed groups whose entries hold only tracked keys, that write is recorded, and the container restarts with only one group's variables
- **THEN** the Generated config SHALL NOT contain the removed tracked group
- **AND** the remaining tracked group SHALL be present under its group name with its current values

#### Scenario: Untracked key inside group survives

- **WHEN** a tracked name-keyed group entry also holds a never-tracked key in the Base config and the container restarts without any variable setting that group list
- **THEN** the Generated config SHALL retain that never-tracked key in the entry identified by the group name
- **AND** the Generated config SHALL NOT contain the removed tracked keys of that group

### Requirement: Env key tracking record

Each time the Generated config is written, the keys set from `ENSHROUDED_*` variables SHALL be recorded in the tracking file `/data/config/.enshrouded-tracked.json`, separate from the Generated config. The record SHALL carry a version plus tracked key paths only and SHALL NOT contain environment values. Config generation without a write SHALL NOT change the record.

#### Scenario: Tracking file is the sidecar record

- **WHEN** the Generated config is written
- **THEN** the tracking file at `/data/config/.enshrouded-tracked.json` SHALL exist separate from the Generated config and SHALL carry a version

#### Scenario: Tracking file holds no values

- **WHEN** the Generated config is written with a group password set from the environment
- **THEN** the tracking file SHALL record the password key's path
- **AND** the tracking file SHALL NOT contain the password value

#### Scenario: No history keeps existing keys

- **WHEN** the persisted config contains a key, no tracking file exists, and the container restarts without any variable setting that key
- **THEN** the Generated config SHALL retain that key

#### Scenario: Unusable tracking file removes nothing

- **WHEN** the tracking file exists but cannot be read as a valid tracking file, including an unsupported version
- **THEN** a warning SHALL be logged, no key SHALL be removed as stale, and config generation SHALL succeed

#### Scenario: Missing persisted config resets tracking

- **WHEN** no persisted config exists so the Example config is the Base config, a tracking file from an earlier persisted config records a key the Example config defines, and the container restarts without any variable setting that key
- **THEN** the Generated config SHALL retain the Example config value for that key

#### Scenario: Preview does not persist tracking

- **WHEN** config generation is previewed through `debug-config` with a variable removed since the last write
- **THEN** the preview SHALL show the stale key removed
- **AND** the persisted config and the tracking file SHALL NOT change

### Requirement: Generated config placement and ownership

The Generated config SHALL be written to the config directory after applying all env var overrides. The persisted config file and the tracking file SHALL be owned by the configured `PUID`/`PGID` (see `shared-config` for where ownership values originate). The tracking file SHALL be written atomically after the Generated config; failing to write it SHALL log a warning and SHALL NOT fail config generation.

#### Scenario: Config is written to config dir

- **WHEN** config generation completes
- **THEN** the persisted config file SHALL exist with the merged configuration

#### Scenario: Config overrides are applied to base

- **WHEN** a Base config names a server and an env var overrides that name
- **THEN** the output SHALL contain the overridden name

#### Scenario: Config file owned by configured user

- **WHEN** config generation completes with ownership configured
- **THEN** the persisted config file SHALL be owned by the configured user and group

#### Scenario: Tracking write failure does not fail generation

- **WHEN** the tracking file cannot be written after the Generated config is written
- **THEN** a warning SHALL be logged
- **AND** the Generated config SHALL remain written and usable

#### Scenario: Tracking file owned by configured user

- **WHEN** config generation completes with ownership configured
- **THEN** the tracking file SHALL be owned by the configured user and group

#### Scenario: Tracking write survives interruption

- **WHEN** the process stops during a tracking file write
- **THEN** the next start SHALL observe a complete previous or new tracking file, never a partial tracking file

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
