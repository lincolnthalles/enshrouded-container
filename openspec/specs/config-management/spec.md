## Requirements

### Requirement: Non-mutating config merge

The `deep_merge` function in `enshctl.config` SHALL return a new dictionary without mutating the base dictionary. The `generate_config` function SHALL call `deep_merge` and use the returned result.

#### Scenario: Base config preserved after merge

- **WHEN** `generate_config()` is called with a base config loaded from file
- **THEN** the original base config dict SHALL not be modified by the merge operation

### Requirement: Settings integration

The `generate_config` and `write_config` functions SHALL accept an optional `AppSettings` parameter for accessing `PUID`/`PGID` values instead of reading `os.environ` directly. If not provided, they SHALL fall back to loading settings from the environment.

#### Scenario: Settings passed explicitly

- **WHEN** `write_config(config, settings=AppSettings(puid=1001, pgid=1002))` is called
- **THEN** the config file SHALL be owned by uid 1001, gid 1002

#### Scenario: Settings loaded from env when not provided

- **WHEN** `write_config(config)` is called with `PUID=1000` in environment
- **THEN** the config file SHALL be owned by uid 1000

### Requirement: Config file injection

The container SHALL accept an `enshrouded_server.json` file mounted at `/data/config/enshrouded_server.json`. If present, this file SHALL serve as the base configuration that environment variable overrides apply to. If absent, the script SHALL extract the default config from the game install.

#### Scenario: User-provided config is used as base

- **WHEN** `/data/config/enshrouded_server.json` exists
- **THEN** its contents SHALL be used as the base configuration

#### Scenario: No user config, game default is used

- **WHEN** `/data/config/enshrouded_server.json` does not exist
- **THEN** the default config SHALL be extracted from the game install at `/data/gameserver/enshrouded_server_example.json`

### Requirement: Env var to JSON conversion

Environment variables with the prefix `ENSHROUDED_` SHALL be converted to nested JSON keys and merged into the base configuration. The conversion SHALL be case-insensitive for the prefix but case-preserving for the key segments.

#### Scenario: Simple string setting

- **WHEN** `ENSHROUDED_NAME=My Server` is set
- **THEN** the generated config SHALL contain `{"name": "My Server"}`

#### Scenario: Nested setting with dot-path segments

- **WHEN** `ENSHROUDED_GAME_SETTINGS_PLAYER_HEALTH_FACTOR=2` is set
- **THEN** the generated config SHALL contain `{"gameSettings": {"playerHealthFactor": 2}}`

#### Scenario: Boolean value detection

- **WHEN** `ENSHROUDED_GAME_SETTINGS_IS_PVP=true` is set
- **THEN** the generated config SHALL contain `{"gameSettings": {"isPVP": true}}` (boolean, not string)

#### Scenario: Integer value detection

- **WHEN** `ENSHROUDED_SLOT_COUNT=16` is set
- **THEN** the generated config SHALL contain `{"slotCount": 16}` (integer, not string)

#### Scenario: Float value detection

- **WHEN** `ENSHROUDED_GAME_SETTINGS_DAY_TIME_FACTOR=1.5` is set
- **THEN** the generated config SHALL contain `{"gameSettings": {"dayTimeFactor": 1.5}}`

#### Scenario: JSON array value

- **WHEN** `ENSHROUDED_GAME_SETTINGS_ALLOWED_ITEMS=["sword","shield"]` is set
- **THEN** the generated config SHALL contain `{"gameSettings": {"allowedItems": ["sword", "shield"]}}`

#### Scenario: Env var without prefix is ignored

- **WHEN** `SERVER_NAME=Test` is set (no ENSHROUDED_ prefix)
- **THEN** the env var SHALL NOT affect the generated config

#### Scenario: Config is schema-agnostic

- **WHEN** `ENSHROUDED_FUTURE_SETTING_NEW_FEATURE=enabled` is set
- **THEN** the generated config SHALL contain `{"futureSetting": {"newFeature": "enabled"}}` regardless of whether the current game server schema defines that key

### Requirement: Config file placement

The generated `enshrouded_server.json` SHALL be written to the config directory (`/data/config/enshrouded_server.json`) after applying all env var overrides. The game server SHALL read this file on startup.

#### Scenario: Config is written to config dir

- **WHEN** config generation completes
- **THEN** `/data/config/enshrouded_server.json` SHALL exist with the merged configuration

#### Scenario: Config overrides are applied to base

- **WHEN** a user-provided base config at `/data/config/enshrouded_server.json` contains `{"name": "Base"}` and `ENSHROUDED_NAME=Override` is set
- **THEN** the output SHALL contain `{"name": "Override"}`

### Requirement: Naming convention transformation

The segment transformation SHALL convert SCREAMING_SNAKE_CASE to lowerCamelCase using the following rules: split on `_`, lowercase the first segment entirely, then capitalize the first letter of each subsequent segment.

#### Scenario: Single segment

- **WHEN** the key after prefix removal is `NAME`
- **THEN** the JSON key SHALL be `name`

#### Scenario: Multi-segment

- **WHEN** the key after prefix removal is `GAME_SETTINGS_PLAYER_HEALTH_FACTOR`
- **THEN** the JSON path SHALL be `gameSettings.playerHealthFactor`

#### Scenario: Acronym preservation

- **WHEN** the key after prefix removal is `SERVER_IP`
- **THEN** the JSON key SHALL be `serverIP`

#### Scenario: Lowercase input

- **WHEN** the key is already lowercase (e.g., `enshrouded_name`)
- **THEN** the JSON key SHALL be `name` (first segment remains lowercase)
