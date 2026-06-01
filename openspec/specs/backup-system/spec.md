## Requirements

### Requirement: Backup module structure

The backup system SHALL be organized as a `backup/` subpackage with the following modules: `__init__.py` (re-exports public API), `locking.py` (file lock management), `archive.py` (compression/decompression/verification), `core.py` (format/level selection, disk space checks, cron parsing, constants). The public API SHALL remain backward compatible — all existing imports from `enshctl.backup` SHALL continue to work.

#### Scenario: Backward compatible imports

- **WHEN** code imports `from enshctl.backup import create_backup, acquire_lock, parse_cron`
- **THEN** the imports SHALL succeed without changes

#### Scenario: Locking isolated

- **WHEN** `acquire_lock` and `release_lock` are needed
- **THEN** they SHALL be defined in `enshctl/backup/locking.py` and re-exported from `__init__.py`

### Requirement: Cron-driven backups

The container SHALL run periodic backups of `/data/saves` on a configurable cron schedule. The default interval SHALL be every 60 minutes (`*/60 * * * *`). The `BACKUP_CRON` env var SHALL override the schedule. Each backup SHALL be spawned as a subprocess with lowered priority.

#### Scenario: Default backup interval

- **WHEN** `BACKUP_CRON` is not set and the container is running
- **THEN** a backup subprocess SHALL be spawned every 60 minutes

#### Scenario: Custom backup interval

- **WHEN** `BACKUP_CRON=*/5 * * * *` is set
- **THEN** a backup subprocess SHALL be spawned every 5 minutes

### Requirement: Cron parser warns on unsupported fields

The `parse_cron` function SHALL log a WARNING when hours, days, months, or weekday fields contain non-`*` values (excluding `*/N` patterns in the minute field). The function SHALL still return an interval based on the minute field, but the warning SHALL inform the user that other fields are ignored.

#### Scenario: Standard cron expression with hour field

- **WHEN** `parse_cron("0 2 * * *")` is called
- **THEN** it SHALL log a warning that the hour field (`2`) is ignored and return an interval based on minute `0`

#### Scenario: Minute-only cron expression

- **WHEN** `parse_cron("*/30 * * * *")` is called
- **THEN** it SHALL NOT log a warning and SHALL return `1800.0`

#### Scenario: Unsupported minute field

- **WHEN** `parse_cron("15,45 * * * *")` is called (comma-separated list)
- **THEN** it SHALL log a warning about unsupported cron syntax and return `1200.0` (default fallback)

### Requirement: Backup compression

Backups SHALL support configurable compression formats (zstd, gzip, zip) and compression levels. The `BACKUP_FORMAT` env var SHALL set the default format (default: `zstd`). The `BACKUP_LEVEL` env var SHALL set the default level (default: `9`). Levels SHALL be clamped to the format's maximum with a warning log if exceeded.

#### Scenario: Default compression

- **WHEN** `BACKUP_FORMAT` and `BACKUP_LEVEL` are not set and a backup is triggered
- **THEN** the output file SHALL be a valid zstd-compressed tar archive at level 9

#### Scenario: Gzip compression

- **WHEN** `BACKUP_FORMAT=gzip` is set and a backup is triggered
- **THEN** the output file SHALL be a valid gzip-compressed tar archive with `.tar.gz` extension

#### Scenario: Zip compression

- **WHEN** `BACKUP_FORMAT=zip` is set and a backup is triggered
- **THEN** the output file SHALL be a valid zip archive with `.zip` extension

#### Scenario: Compression level clamped

- **WHEN** `BACKUP_FORMAT=gzip` and `BACKUP_LEVEL=15` are set
- **THEN** the level SHALL be clamped to 9 (gzip max) with a warning log

#### Scenario: Level via CLI flag

- **WHEN** `enshctl backup --format zstd --level 19` is executed
- **THEN** the backup SHALL use zstd compression at level 19

### Requirement: Shutdown-triggered backup

When the container receives SIGTERM and `BACKUP_COLD=1`, the entrypoint SHALL spawn a cold backup subprocess (`enshctl backup --cold`) in its own session (`start_new_session=True`) so it survives the parent's SIGTERM. The cold backup SHALL run after the game server exits and after any in-progress scheduled backup completes, but BEFORE Wine server cleanup.

#### Scenario: Cold backup on shutdown

- **WHEN** the container receives SIGTERM and `BACKUP_COLD=1` and `/data/saves` has data
- **THEN** a cold backup subprocess SHALL be spawned with `start_new_session=True` and SHALL complete even if Docker sends SIGKILL to the parent's process group

#### Scenario: Cold backup runs before Wine cleanup

- **WHEN** the container receives SIGTERM and the game server has exited
- **THEN** the cold backup SHALL complete before Wine server cleanup runs, ensuring save data is captured in a clean state

#### Scenario: Cold backup waits for in-progress backup

- **WHEN** the container receives SIGTERM and a scheduled backup subprocess is running
- **THEN** the handler SHALL wait for the scheduled backup to finish before spawning the cold backup

#### Scenario: Cold backup disabled

- **WHEN** the container receives SIGTERM and `BACKUP_COLD=0`
- **THEN** no cold backup SHALL be created

#### Scenario: Shutdown backup with no save data

- **WHEN** the container receives SIGTERM and `/data/saves` is empty or does not exist
- **THEN** no backup SHALL be created and the container SHALL exit cleanly

### Requirement: Backup retention

**Reason**: Replaced by time-based retention system (see `backup-prune` capability).

**Migration**: `BACKUP_RETENTION` env var is removed. Use `BACKUP_KEEP_LAST`, `BACKUP_KEEP_HOURLY`, `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`, `BACKUP_KEEP_MONTHLY`, `BACKUP_KEEP_YEARLY` instead. Set `BACKUP_KEEP_LAST=<N>` to replicate the old count-based behavior.

#### Scenario: BACKUP_RETENTION removed

- **WHEN** `BACKUP_RETENTION` is set in the environment
- **THEN** the value SHALL be ignored and a warning SHALL be logged indicating the migration path

### Requirement: Backup directory

Backups SHALL be stored in category subdirectories under `/data/backups/`: `live/` for scheduled backups, `cold/` for graceful shutdown backups, `emergency/` for unexpected exit backups. The `BACKUP_DIR` env var SHALL override the base path.

#### Scenario: Scheduled backup writes to live/

- **WHEN** a scheduled backup triggers
- **THEN** the backup file SHALL be written to `/data/backups/live/`

#### Scenario: Cold backup writes to cold/

- **WHEN** a cold backup triggers
- **THEN** the backup file SHALL be written to `/data/backups/cold/`

#### Scenario: Emergency backup writes to emergency/

- **WHEN** an emergency backup triggers
- **THEN** the backup file SHALL be written to `/data/backups/emergency/`

#### Scenario: Custom base directory

- **WHEN** `BACKUP_DIR=/mnt/nfs/backups` is set
- **THEN** backups SHALL be written to `/mnt/nfs/backups/{live,cold,emergency}/`

### Requirement: Backup filename format

Backup filenames SHALL follow the pattern `enshrouded-YYYYMMDD-HHMMSS[-cold|-emergency].<ext>` where `<ext>` is determined by the compression format: `tar.zst`, `tar.gz`, or `zip`.

#### Scenario: Live backup filename

- **WHEN** a live backup is created at 2026-05-29 12:00:00 UTC with zstd format
- **THEN** the filename SHALL be `enshrouded-20260529-120000.tar.zst`

#### Scenario: Cold backup filename

- **WHEN** a cold backup is created at 2026-05-29 18:00:00 UTC with zstd format
- **THEN** the filename SHALL be `enshrouded-20260529-180000-cold.tar.zst`

#### Scenario: Emergency backup filename with gzip

- **WHEN** an emergency backup is created at 2026-05-29 03:45:22 UTC with gzip format
- **THEN** the filename SHALL be `enshrouded-20260529-034522-emergency.tar.gz`

### Requirement: Emergency backup on crash

When the game server exits unexpectedly and `BACKUP_EMERGENCY=1`, the entrypoint SHALL spawn an emergency backup subprocess (`enshctl backup --emergency`) in its own session (`start_new_session=True`).

#### Scenario: Emergency backup on unexpected exit

- **WHEN** the game server exits with a non-zero code (not SIGTERM-initiated) and `BACKUP_EMERGENCY=1`
- **THEN** an emergency backup subprocess SHALL be spawned with `start_new_session=True` and SHALL complete independently of the parent process

#### Scenario: Emergency backup disabled

- **WHEN** the game server exits unexpectedly and `BACKUP_EMERGENCY=0`
- **THEN** no emergency backup SHALL be created
