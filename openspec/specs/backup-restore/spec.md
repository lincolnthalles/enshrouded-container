## Purpose

Restore of world save data from a selected backup archive.

## Requirements

### Requirement: Restore safety check

Before restoring, the system SHALL check if the game server process is running. If running, the system SHALL refuse to restore and exit with an error.

#### Scenario: Refuse restore while server runs

- **WHEN** `enshrouded_server.exe` process is detected
- **THEN** the restore command SHALL exit with an error message "Cannot restore while server is running"

### Requirement: Restore from backup by filename

The `restore` subcommand SHALL restore a specific backup to `/data/saves/` when given a full filename via `--file`.

#### Scenario: Restore specific backup

- **WHEN** `enshrouded-server restore --file enshrouded-20260529-120000.tar.zst` is executed and the game server is not running
- **THEN** `/data/saves/` SHALL be emptied and the contents of the specified backup SHALL be extracted into it

#### Scenario: Restore refuses if server is running

- **WHEN** `enshrouded-server restore --file ...` is executed and `enshrouded_server.exe` process is detected
- **THEN** the command SHALL refuse to proceed and exit with an error message indicating the server must be stopped first

### Requirement: Restore from backup by direction

The `restore` subcommand SHALL select the best-matching backup when given a `--when` direction. Directions are relative time windows: `last` (newest overall), `30m`, `1h`, `30d`, `3M`. The command SHALL select the newest backup within the specified window. A category qualifier may be appended with colon syntax: `last:live`, `30d:cold`, `1h:emergency`.

#### Scenario: Restore most recent backup

- **WHEN** `enshrouded-server restore --when last` is executed and backups exist in all categories
- **THEN** the newest backup across all categories SHALL be selected for restore

#### Scenario: Restore with time window

- **WHEN** `enshrouded-server restore --when 30d` is executed
- **THEN** the newest backup created within the last 30 days SHALL be selected for restore

#### Scenario: Restore with category qualifier

- **WHEN** `enshrouded-server restore --when 30d:cold` is executed
- **THEN** the newest cold backup within the last 30 days SHALL be selected

#### Scenario: No backup matches direction

- **WHEN** `enshrouded-server restore --when 1h` is executed and no backup exists within the last hour
- **THEN** the command SHALL report no matching backup and exit with a non-zero code

### Requirement: Interactive restore picker

When neither `--file` nor `--when` is provided and stdout is a TTY, the `restore` subcommand SHALL present an interactive Textual TUI picker. The picker SHALL display a flat list of available backups as `name (size)` entries and return the selected backup's path.

#### Scenario: Interactive restore on TTY

- **WHEN** `enshrouded-server restore` is executed in a TTY without `--file` or `--when`
- **THEN** an interactive picker SHALL be displayed showing each backup as `name (size)`; category drill-in, counts, and timestamps are not shown

#### Scenario: Interactive restore falls back on non-TTY

- **WHEN** `enshrouded-server restore` is executed without `--file` or `--when` and stdout is not a TTY
- **THEN** the command SHALL print available backups as a table and exit (equivalent to `--list`)

### Requirement: List backups

The `restore --list` flag SHALL list all backups as a Rich table (TTY) or plain text (non-TTY) and exit. The `--when` flag is accepted by the parser but SHALL be ignored in list mode; all backups are listed unfiltered.

#### Scenario: List all backups

- **WHEN** `enshrouded-server restore --list` is executed
- **THEN** a table SHALL be printed showing all backups across all categories with filename, category, size, and timestamp

### Requirement: Restore confirmation prompt

Before restoring, the command SHALL prompt for confirmation showing the backup filename and size. The `--yes` flag SHALL skip the prompt.

#### Scenario: Confirmation prompt displayed

- **WHEN** a backup is selected for restore and `--yes` is not set
- **THEN** a prompt SHALL display: "Restore `<filename>` (`<size>`) to /data/saves? This will erase current saves. [y/N]"

#### Scenario: Confirmation skipped with --yes

- **WHEN** `enshrouded-server restore --file ... --yes` is executed
- **THEN** the restore SHALL proceed without prompting

### Requirement: Restore process

The restore process SHALL: (1) acquire the backup lock, (2) remove all contents of `/data/saves/`, (3) extract the backup archive into `/data/saves/`, (4) release the lock.

#### Scenario: Successful restore

- **WHEN** restore proceeds after confirmation
- **THEN** `/data/saves/` SHALL contain exactly the contents of the selected backup archive

#### Scenario: Restore holds lock

- **WHEN** restore is in progress
- **THEN** no backup operation SHALL be able to acquire the lock concurrently
