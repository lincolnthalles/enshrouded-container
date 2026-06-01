### Requirement: Game tree rebuild on startup

At container startup, the entrypoint SHALL construct `/data/gameserver/` as a symlink tree pointing to manifest and mod files. The directory SHALL be wiped and rebuilt from scratch on every start.

#### Scenario: Fresh start with manifest files

- **WHEN** the container starts and a manifest is installed at `/data/manifests/<version>/`
- **THEN** all files from the manifest SHALL be symlinked into `/data/gameserver/` using `cp -as`
- **AND** `/data/gameserver/enshrouded_server.json` SHALL be a symlink to `/data/config/enshrouded_server.json`

#### Scenario: Mods override manifest files

- **WHEN** the container starts and `/data/mods/` contains files
- **THEN** mod files SHALL be symlinked over the manifest symlinks using `cp -as`
- **AND** files present in both manifest and mods SHALL resolve to the mod version

#### Scenario: Wipe on every start

- **WHEN** the container starts
- **THEN** all existing contents of `/data/gameserver/` SHALL be removed before rebuilding
- **AND** the wipe SHALL NOT delete source files in `/data/manifests/` or `/data/config/`

### Requirement: Config symlink

The config file at `/data/gameserver/enshrouded_server.json` SHALL be a symlink to `/data/config/enshrouded_server.json`. The config generator SHALL read from and write to `/data/config/enshrouded_server.json` directly.

#### Scenario: First run creates config

- **WHEN** the container starts and `/data/config/enshrouded_server.json` does not exist
- **THEN** the config generator SHALL fall back to the example JSON from the manifest
- **AND** write the generated config to `/data/config/enshrouded_server.json`
- **AND** the symlink at `/data/gameserver/enshrouded_server.json` SHALL resolve to the generated file

#### Scenario: Config persistence across restarts

- **WHEN** the game server modifies `enshrouded_server.json` at runtime (e.g. banned players)
- **THEN** the modifications SHALL persist to `/data/config/enshrouded_server.json`
- **AND** on next startup, `load_base_config` SHALL read the persisted (modified) file
- **AND** env vars SHALL be merged on top, overriding only keys that have env var values

### Requirement: PERSIST_FILES escape hatch

An environment variable `PERSIST_FILES` SHALL accept a comma-separated list of relative file paths. Files listed SHALL be copied from the manifest to `/data/config/` (if not already present) and symlinked from `/data/gameserver/` to `/data/config/`.

#### Scenario: Default PERSIST_FILES

- **WHEN** `PERSIST_FILES` is not set
- **THEN** `enshrouded_server.json` SHALL be the only persisted file

#### Scenario: Custom PERSIST_FILES

- **WHEN** `PERSIST_FILES=enshrouded_server.json,runtime_state.dat`
- **THEN** `runtime_state.dat` SHALL be copied from the manifest to `/data/config/runtime_state.dat` (first run only)
- **AND** symlinked from `/data/gameserver/runtime_state.dat` to `/data/config/runtime_state.dat`

### Requirement: Manifest read-only protection

After downloading a manifest, the orchestrator SHALL remove write permissions from all files in the manifest directory.

#### Scenario: Manifest marked read-only after download

- **WHEN** a manifest is downloaded to `/data/manifests/<version>/`
- **THEN** `chmod -R a-w` SHALL be applied to the manifest directory
- **AND** all files in the manifest SHALL have write permission removed for all users

#### Scenario: Read-only prevents accidental modification

- **WHEN** a process attempts to write to a file symlinked from the manifest
- **THEN** the write SHALL fail with a permission error
