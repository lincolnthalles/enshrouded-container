## Purpose

Persistent world save data volume and its wiring into the generated server config.

## Requirements

### Requirement: Saved games volume

The container SHALL expose `/data/saves` as a volume for persistent world save data. The `saveDirectory` field in the generated `enshrouded_server.json` SHALL be an absolute path defaulting to `/data/saves`. Relative values from any source (base config file, `ENSHROUDED_SAVE_DIRECTORY`) SHALL be remapped to `/data/saves` with a warning, since the game resolves them against the ephemeral `/data/gameserver` tree.

#### Scenario: Save directory is configured

- **WHEN** the config is generated with no save directory configured
- **THEN** `saveDirectory` in `enshrouded_server.json` SHALL be set to `/data/saves`

#### Scenario: Relative save directory remapped

- **WHEN** the base config or `ENSHROUDED_SAVE_DIRECTORY` provides `./savegame`
- **THEN** `saveDirectory` SHALL be `/data/saves` and a warning SHALL name the discarded value

#### Scenario: Absolute save directory preserved

- **WHEN** `ENSHROUDED_SAVE_DIRECTORY=/mnt/nfs/enshrouded` is set
- **THEN** `saveDirectory` SHALL be `/mnt/nfs/enshrouded` with no warning

#### Scenario: Save directory is writable

- **WHEN** the game server starts
- **THEN** the server SHALL be able to write save files to `/data/saves`

#### Scenario: Save directory persists across restarts

- **WHEN** the container is stopped and restarted with the same volume
- **THEN** previously saved world data SHALL still be present in `/data/saves`

### Requirement: Log directory

The container SHALL set `logDirectory` in the generated config to the absolute path `/data/logs` by default. Relative values SHALL be remapped to `/data/logs` with a warning, mirroring the save directory rule. The game writes identical content to its log file and to stdout; the orchestrator relays stdout to the console, so no log-file symlinking or tailing is required for Docker log collection.

#### Scenario: Log directory is configured

- **WHEN** the config is generated with no log directory configured
- **THEN** `logDirectory` in `enshrouded_server.json` SHALL be set to `/data/logs`

#### Scenario: Relative log directory remapped

- **WHEN** the base config or `ENSHROUDED_LOG_DIRECTORY` provides `./logs`
- **THEN** `logDirectory` SHALL be `/data/logs` and a warning SHALL name the discarded value

#### Scenario: Logs are visible in docker logs

- **WHEN** the server runs
- **THEN** `docker logs` SHALL display the server output via the orchestrator's stdout relay, without any log-file symlink or tail process

### Requirement: Save directory env var override

The `saveDirectory` field SHALL be overridable via `ENSHROUDED_SAVE_DIRECTORY` with an absolute path. If set to an absolute path, it SHALL take precedence over the default `/data/saves`. Relative values SHALL be remapped per the saved-games-volume requirement.

#### Scenario: Custom save directory

- **WHEN** `ENSHROUDED_SAVE_DIRECTORY=/mnt/nfs/enshrouded` is set
- **THEN** `saveDirectory` in the config SHALL be `/mnt/nfs/enshrouded`

### Requirement: Restore extracts to temporary directory first

The restore operation SHALL extract the backup archive to a temporary directory (`/data/saves-restore-tmp/`) before modifying `/data/saves/`. If extraction fails for any reason (ENOSPC, corrupt archive, etc.), the temporary directory SHALL be cleaned up and `/data/saves/` SHALL remain untouched.

#### Scenario: Successful extraction then swap

- **WHEN** the user confirms restore and extraction to tmp succeeds
- **THEN** the system SHALL clear `/data/saves/` contents, move each item from tmp to saves via `shutil.move`, and remove the empty tmp directory

#### Scenario: Extraction fails from ENOSPC

- **WHEN** extraction to tmp fails because the disk fills mid-write
- **THEN** the system SHALL clean up tmp, log the error with current free space, and exit with code 1 without modifying saves

#### Scenario: Extraction fails from corrupt archive

- **WHEN** extraction to tmp fails because the archive is corrupt
- **THEN** the system SHALL clean up tmp and exit with code 1 without modifying saves

#### Scenario: Temporary directory cleaned on success

- **WHEN** the restore completes successfully
- **THEN** `/data/saves-restore-tmp/` SHALL NOT exist

#### Scenario: Existing temporary directory handled

- **WHEN** a restore begins and `/data/saves-restore-tmp/` already exists
- **THEN** the existing tmp directory SHALL be removed before extraction starts
