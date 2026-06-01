## Requirements

### Requirement: Saved games volume

The container SHALL expose `/data/saves` as a volume for persistent world save data. The `saveDirectory` field in the generated `enshrouded_server.json` SHALL be set to `/data/saves`.

#### Scenario: Save directory is configured

- **WHEN** the config is generated
- **THEN** `saveDirectory` in `enshrouded_server.json` SHALL be set to `/data/saves`

#### Scenario: Save directory is writable

- **WHEN** the game server starts
- **THEN** the server SHALL be able to write save files to `/data/saves`

#### Scenario: Save directory persists across restarts

- **WHEN** the container is stopped and restarted with the same volume
- **THEN** previously saved world data SHALL still be present in `/data/saves`

### Requirement: Log directory

The container SHALL set `logDirectory` in the generated config to `/data/logs`. Server logs SHALL be written to `/data/logs/` and SHALL be symlinked to stdout for Docker log collection.

#### Scenario: Log directory is configured

- **WHEN** the config is generated
- **THEN** `logDirectory` in `enshrouded_server.json` SHALL be set to `/data/logs`

#### Scenario: Logs are visible in docker logs

- **WHEN** the server writes to its log file
- **THEN** `docker logs` SHALL display the log output

### Requirement: Save directory env var override

The `saveDirectory` field SHALL be overridable via `ENSHROUDED_SAVE_DIRECTORY`. If set, it SHALL take precedence over the default `/data/saves`.

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
