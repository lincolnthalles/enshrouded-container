## Purpose

Restore of world save data from a selected Backup; atomic swap keeps saves consistent.

## Requirements

### Requirement: Running-server guard

Before restoring a selected Backup, the command SHALL refuse when the orchestrator considers the server running (PID file present) and exit with an error directing the user to stop the server first. Selection happens first: an unknown filename, an unmatched direction, or quitting the picker SHALL report no match without reaching the guard. Listing SHALL never trigger the guard.

#### Scenario: Refuse restore while server runs

- **WHEN** a restore is requested for an existing Backup and the PID file exists
- **THEN** the restore command SHALL exit with an error directing the user to stop the server first

#### Scenario: No match precedes guard

- **WHEN** `restore --file` names a file present in no Category and the PID file exists
- **THEN** the command SHALL report no matching Backup (not the stop-server error) and exit with a non-zero code

#### Scenario: List mode exempt from guard

- **WHEN** `restore --list` is executed and the PID file exists
- **THEN** the command SHALL list Backups normally without refusing

### Requirement: Restore from Backup by filename

The `restore --file` invocation SHALL restore a specific stored file by filename, searching every Category by presence (grammar-matching Backup or not), rejecting absolute paths, parent-directory escapes, and directories. Selection precedes the server guard.

#### Scenario: Restore specific Backup

- **WHEN** `restore --file` names an existing Backup and the game server is not running
- **THEN** the saves directory SHALL end up containing exactly the contents of the specified Backup

#### Scenario: Non-Backup file accepted by presence

- **WHEN** `restore --file` names a non-grammar file present in a Category directory
- **THEN** that file SHALL be restored like any Backup; selection by presence is owned here (see `backup-verify` for the reporting side)

#### Scenario: Path escape rejected as no match

- **WHEN** `restore --file` names an absolute path, a parent-directory escape, or a directory
- **THEN** the command SHALL report no match and exit with a non-zero code

#### Scenario: Unknown filename exits non-zero

- **WHEN** `restore --file` names a file present in no Category
- **THEN** the command SHALL report no match and exit with a non-zero code

### Requirement: Restore from Backup by direction

The `restore --when` invocation SHALL select the newest Backup within a relative time window: `last` for the newest overall, otherwise a count plus unit (`m` minutes, `h` hours, `d` days, `M` 30-day blocks). A Category qualifier may be appended with colon syntax (`30d:cold`); an empty qualifier means all Categories. An unknown Category or unparseable direction SHALL report no match and exit with a non-zero code.

#### Scenario: Restore most recent Backup

- **WHEN** `restore --when last` is executed and Backups exist across Categories
- **THEN** the newest Backup across all Categories SHALL be selected for restore

#### Scenario: Restore with time window

- **WHEN** `restore --when 30d` is executed
- **THEN** the newest Backup created within the last 30 days SHALL be selected for restore

#### Scenario: Restore with Category qualifier

- **WHEN** `restore --when 30d:cold` is executed
- **THEN** the newest cold-Category Backup within the last 30 days SHALL be selected

#### Scenario: Empty qualifier means all Categories

- **WHEN** `restore --when last:` is executed
- **THEN** the newest Backup across all Categories SHALL be selected for restore

#### Scenario: Unknown Category reports no match

- **WHEN** `restore --when 30d:bogus` is executed
- **THEN** the command SHALL report no matching Backup and exit with a non-zero code

#### Scenario: No Backup matches direction

- **WHEN** `restore --when 1h` is executed and no Backup exists within the last hour
- **THEN** the command SHALL report no matching Backup and exit with a non-zero code

### Requirement: Interactive restore picker

When neither `--file` nor `--when` is provided, the command SHALL present an interactive picker on a TTY showing each Backup with its size, and SHALL list and exit on a non-TTY.

#### Scenario: Interactive restore on TTY

- **WHEN** `restore` is executed in a TTY without `--file` or `--when`
- **THEN** an interactive picker SHALL display each Backup with its size for selection

#### Scenario: Interactive restore falls back on non-TTY

- **WHEN** `restore` is executed without `--file` or `--when` and stdout is not a TTY
- **THEN** the command SHALL print available Backups as a table and exit (equivalent to `--list`)

### Requirement: List Backups

The `restore --list` invocation SHALL take precedence over `--file`/`--when`: it lists all Backups with filename, Category, size, and timestamp, and exits without restoring. With no Backups present, it SHALL log that none were found and exit 0 without printing a table.

#### Scenario: List all Backups

- **WHEN** `restore --list` is executed
- **THEN** a table SHALL be printed showing all Backups across all Categories with filename, Category, size, and timestamp

#### Scenario: List ignores selection flags

- **WHEN** `restore --list --when last` is executed
- **THEN** all Backups SHALL be listed unfiltered and nothing SHALL be restored

#### Scenario: List with no Backups

- **WHEN** `restore --list` is executed and no Backups exist
- **THEN** the command SHALL log that no Backups were found and exit 0 without printing a table

### Requirement: Restore confirmation prompt

After selection and the server guard pass, and before acquiring the lock, the command SHALL prompt for confirmation showing the Backup filename and size. The `--yes` flag SHALL skip the prompt; declining SHALL cancel without touching saves.

#### Scenario: Confirmation prompt displayed

- **WHEN** a Backup is selected for restore and `--yes` is not set
- **THEN** a prompt SHALL display the filename and size and warn that current saves will be erased

#### Scenario: Confirmation skipped with --yes

- **WHEN** `restore --file ... --yes` is executed
- **THEN** the restore SHALL proceed without prompting

#### Scenario: Declined restore cancels

- **WHEN** the confirmation prompt is declined
- **THEN** the command SHALL exit without modifying the saves directory

### Requirement: Atomic restore swap

The restore SHALL extract the Backup to the temporary directory (`/data/saves-restore-tmp/`), verify space (see `disk-space-guards`), then clear the saves directory and move the extracted contents in. While a restore runs, no Backup operation SHALL acquire the lock concurrently (see `backup-subprocess`). A failure during clear or move SHALL clean up the temporary directory, log the error, and exit 1; the saves directory may be partially modified in that case.

#### Scenario: Successful extraction then swap

- **WHEN** the user confirms restore and extraction to tmp succeeds with space verified
- **THEN** the saves directory SHALL contain exactly the contents of the selected Backup and the temporary directory SHALL NOT exist

#### Scenario: Failed extraction leaves saves untouched

- **WHEN** extraction to tmp fails because the Backup is corrupt or the disk fills mid-write
- **THEN** the temporary directory SHALL be cleaned up, the error SHALL name the cause with current free space, the saves directory SHALL remain untouched, and the command SHALL exit 1

#### Scenario: Space shortfall before clearing leaves saves untouched

- **WHEN** extraction succeeds but the space check fails (see `disk-space-guards`)
- **THEN** the temporary directory SHALL be cleaned up, the saves directory SHALL remain untouched, and the command SHALL exit 1

#### Scenario: Unreadable format fails cleanly

- **WHEN** `restore --file` names a file whose suffix matches no known compression format
- **THEN** the temporary directory SHALL be cleaned up, the saves directory SHALL remain untouched, and the command SHALL exit 1

#### Scenario: Clear or move failure cleans tmp

- **WHEN** clearing saves or moving extracted data fails
- **THEN** the temporary directory SHALL be cleaned up, the error SHALL be logged, and the command SHALL exit 1

#### Scenario: Restore holds lock

- **WHEN** restore is in progress
- **THEN** no Backup operation SHALL be able to acquire the lock concurrently (see `backup-subprocess`)

#### Scenario: Lock contention exits non-zero

- **WHEN** restore is requested and a Backup operation holds the lock
- **THEN** the command SHALL exit with a non-zero code without touching saves

#### Scenario: Existing temporary directory handled

- **WHEN** a restore begins and the temporary directory already exists
- **THEN** the existing tmp directory SHALL be removed before extraction starts
