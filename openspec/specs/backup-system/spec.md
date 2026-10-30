## Purpose

Scheduled, shutdown-triggered, and crash-triggered backups of the saves directory with configurable compression.

## Requirements

### Requirement: Scheduled live backups

The container SHALL run periodic Backups of `/data/saves` in the live Category on a configurable schedule, and SHALL stop the scheduler during shutdown. The default schedule SHALL be every 60 minutes. The first backup SHALL run when the container starts. When live backups are disabled, no scheduler SHALL run. A scheduled trigger with no save data present SHALL skip that backup.

#### Scenario: Default backup schedule

- **WHEN** no schedule is configured, live backups are enabled, and save data exists
- **THEN** a live Backup SHALL be triggered every 60 minutes, starting at container start

#### Scenario: Custom backup schedule

- **WHEN** `BACKUP_CRON` requests every 5 minutes
- **THEN** a live Backup SHALL be triggered every 5 minutes

#### Scenario: Live backups disabled

- **WHEN** `BACKUP_LIVE` disables live backups
- **THEN** no scheduler SHALL run and no scheduled backups SHALL be triggered

#### Scenario: No save data skips scheduled backup

- **WHEN** a scheduled backup triggers with `/data/saves` missing or empty
- **THEN** that backup SHALL be skipped and the scheduler SHALL continue

#### Scenario: Shutdown stops scheduler

- **WHEN** the container receives SIGTERM
- **THEN** no further scheduled backups SHALL be triggered

### Requirement: Minute-level schedule parsing

Backup scheduling SHALL support minute-level cron expressions only. Non-minute fields SHALL be ignored with a warning naming the ignored fields. An unsupported minute field SHALL warn and fall back to a default interval. A malformed schedule expression SHALL log an error and also fall back to the default interval so scheduled backups continue.

#### Scenario: Hour field ignored with warning

- **WHEN** `BACKUP_CRON` includes an hour field value
- **THEN** a warning SHALL name the ignored hour field and the trigger SHALL follow the minute field

#### Scenario: Minute-only schedule accepted

- **WHEN** `BACKUP_CRON` has a `*/30` minute field and no other fields set
- **THEN** no warning SHALL be logged

#### Scenario: Unsupported minute field falls back (including degenerate divisors)

- **WHEN** `BACKUP_CRON` has a comma-separated minute field, or any minute value the scheduler cannot divide by (e.g. `*/0`)
- **THEN** a warning SHALL be logged and the default fallback interval SHALL apply

#### Scenario: Malformed expression falls back

- **WHEN** `BACKUP_CRON` is not a five-field expression
- **THEN** an error SHALL be logged and scheduled backups SHALL continue at the default fallback interval

### Requirement: Backup compression

Backups SHALL support configurable compression formats (zstd, gzip, zip) and compression levels. The format and level SHALL be configurable via `BACKUP_FORMAT` and `BACKUP_LEVEL` env vars (defaults: zstd at format-default level) and per-invocation `--format`/`--level` CLI flags accepting any letter case. An unrecognized format in an env var SHALL fall back to zstd with a warning. Level clamping is per-format with a warning log if exceeded. An unrecognized CLI format flag SHALL reject the command.

#### Scenario: Default compression

- **WHEN** no format or level is configured and a backup is triggered
- **THEN** the output SHALL be a valid zstd-compressed tar archive at the format-default level

#### Scenario: Per-format default levels

- **WHEN** gzip (or zip) format is configured without a level and a backup is triggered
- **THEN** the backup SHALL use that format's default level

#### Scenario: Compression level clamped

- **WHEN** gzip format with an above-maximum level is configured
- **THEN** the level SHALL be clamped to the gzip maximum with a warning log

#### Scenario: Level via CLI flag

- **WHEN** a backup is invoked with zstd format and level 19
- **THEN** the backup SHALL use zstd compression at level 19

#### Scenario: Invalid format flag rejected

- **WHEN** a backup is invoked with an unrecognized `--format` value
- **THEN** the command SHALL exit with code 2

### Requirement: Shutdown-triggered cold backup

When the container receives SIGTERM or SIGINT and cold backups are enabled (`BACKUP_COLD=1`), the shutdown sequence SHALL be: stop the scheduler, send SIGINT to the server and wait up to `SHUTDOWN_TIMEOUT` (default 60s) for it to exit (force-killing after the timeout), create a detached cold backup after any in-progress backup completes (waiting up to `SHUTDOWN_BACKUP_WAIT`, default 120s; see `backup-subprocess` for lock-wait and skip behavior) but BEFORE Wine server cleanup, unless saves are absent.

#### Scenario: Cold backup on shutdown

- **WHEN** the container receives SIGTERM with `BACKUP_COLD=1` and save data present
- **THEN** a detached cold Backup SHALL be created after the server exits and before Wine cleanup, surviving the parent's process group

#### Scenario: Cold backup disabled or no saves

- **WHEN** the container receives SIGTERM with `BACKUP_COLD=0`, or with no save data present
- **THEN** no cold Backup SHALL be created and the entrypoint SHALL exit cleanly

#### Scenario: Force kill after timeout

- **WHEN** the game server does not exit within the shutdown timeout after SIGINT
- **THEN** the entrypoint SHALL send SIGKILL to the process, then proceed to the backup and Wine cleanup steps

#### Scenario: Cold backup waits for in-progress backup

- **WHEN** the container receives SIGTERM and a Backup is already running
- **THEN** the cold Backup SHALL wait up to `SHUTDOWN_BACKUP_WAIT` for it to finish (see `backup-subprocess` for lock-wait and skip behavior)

#### Scenario: Repeat signal ignored

- **WHEN** a second SIGTERM or SIGINT arrives while shutdown is already in progress
- **THEN** the handler SHALL return immediately without restarting the sequence

### Requirement: Obsolete BACKUP_RETENTION setting ignored

When `BACKUP_RETENTION` is set in the environment, the value SHALL be ignored and a warning SHALL name the time-based retention alternatives.

#### Scenario: Stale BACKUP_RETENTION set

- **WHEN** `BACKUP_RETENTION` is set in the environment
- **THEN** the value SHALL be ignored and a warning SHALL name the time-based alternatives

### Requirement: Backup storage layout

Backups SHALL be stored in Category subdirectories (`live`, `cold`, `emergency`) under a configurable base path (default `/data/backups/`).

#### Scenario: Scheduled backup stored in live

- **WHEN** a scheduled Backup triggers
- **THEN** the Backup SHALL be stored in the live Category directory

#### Scenario: Cold backup stored in cold

- **WHEN** a cold Backup triggers
- **THEN** the Backup SHALL be stored in the cold Category directory

#### Scenario: Emergency backup stored in emergency

- **WHEN** an emergency Backup triggers
- **THEN** the Backup SHALL be stored in the emergency Category directory

#### Scenario: Custom base directory

- **WHEN** the backup base directory is set to a custom path
- **THEN** Backups SHALL be stored under that path in the three Category subdirectories

### Requirement: Backup filename format

Backup filenames SHALL follow the pattern `enshrouded-YYYYMMDD-HHMMSS[-cold|-emergency].<ext>` where `<ext>` is determined by the compression format: `tar.zst`, `tar.gz`, or `zip`. Timestamp components SHALL use the container's local wall-clock time; the default container timezone is UTC. No other files in the Category directories are Backups.

#### Scenario: Live backup filename

- **WHEN** a live Backup is created at 2026-05-29 12:00:00 container-local time with zstd format
- **THEN** the filename SHALL be `enshrouded-20260529-120000.tar.zst`

#### Scenario: Cold backup filename

- **WHEN** a cold Backup is created at 2026-05-29 18:00:00 container-local time with zstd format
- **THEN** the filename SHALL be `enshrouded-20260529-180000-cold.tar.zst`

#### Scenario: Emergency backup filename with gzip

- **WHEN** an emergency Backup is created at 2026-05-29 03:45:22 container-local time with gzip format
- **THEN** the filename SHALL be `enshrouded-20260529-034522-emergency.tar.gz`

### Requirement: Emergency backup on crash

When the game server exits unexpectedly (not shutdown-initiated) and emergency backups are enabled (`BACKUP_EMERGENCY=1`) and saves exist, the entrypoint SHALL create a detached emergency backup (see `backup-subprocess` for execution behavior) before exiting with the server's exit code.

#### Scenario: Emergency backup spawned

- **WHEN** the game server exits unexpectedly with emergency backups enabled and save data present
- **THEN** a detached emergency backup SHALL be created and the entrypoint SHALL exit with the server's exit code

#### Scenario: Emergency backup skipped

- **WHEN** the game server exits unexpectedly with `BACKUP_EMERGENCY=0`, or with no save data present
- **THEN** no emergency Backup SHALL be created
