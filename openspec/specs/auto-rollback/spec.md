## Purpose

Scheduled restore of world save data from a configured Backup for Shroud Depot style deployments; startup restore plus wall-clock scheduled stop, restore, and relaunch with presence ignored.

## Requirements

### Requirement: Rollback enablement and selection

Auto rollback SHALL be gated by `ROLLBACK_ENABLED` (default false). When enabled, `ROLLBACK_FILE` SHALL name an exact Backup filename searched across every Category by presence (same selection rule as `restore --file` in `backup-restore`); absolute paths, parent-directory escapes, and directories SHALL count as no match. `ROLLBACK_CRON` SHALL be optional: empty means restore on every container start only. When disabled, `ROLLBACK_FILE` and `ROLLBACK_CRON` SHALL be silently ignored so they can stay configured for future use. `ROLLBACK_ENABLED=true` with an empty, unset, or unmatched `ROLLBACK_FILE` SHALL fail (startup exits non-zero; scheduled ticks log and retry).

#### Scenario: Disabled by default

- **WHEN** the container starts with no rollback settings
- **THEN** no rollback restore SHALL run

#### Scenario: Enabled without a file fails at startup

- **WHEN** `ROLLBACK_ENABLED=true` and `ROLLBACK_FILE` is empty or unset
- **THEN** startup SHALL log an error and exit non-zero without launching the server

#### Scenario: Unknown file fails safe

- **WHEN** `ROLLBACK_ENABLED=true` and `ROLLBACK_FILE` matches no Category by presence
- **THEN** startup SHALL exit non-zero and a scheduled tick SHALL log an error, keep the server running on current saves, and retry at the next tick

#### Scenario: Path escape is no match

- **WHEN** `ROLLBACK_FILE` names an absolute path, a parent-directory escape, or a directory
- **THEN** selection SHALL report no match and fail as an unknown file

### Requirement: Startup restore

When enabled, the container SHALL restore the selected Backup before the first server launch in every mode (with or without `ROLLBACK_CRON`). A lock-held startup restore SHALL fail fast without waiting. A failed startup restore SHALL exit non-zero without launching. After a successful restore, `PUID`/`PGID` ownership SHALL be re-applied to the saves tree (see `save-management`).

#### Scenario: Startup restore in both modes

- **WHEN** `ROLLBACK_ENABLED=true` with a valid `ROLLBACK_FILE`, with or without `ROLLBACK_CRON`
- **THEN** the saves directory SHALL contain exactly the Backup contents before the first launch

#### Scenario: Startup lock contention fails fast

- **WHEN** startup restore runs while another backup operation holds the lock
- **THEN** startup SHALL exit non-zero without touching saves and without waiting

#### Scenario: Restored saves carry game ownership

- **WHEN** a startup or scheduled restore succeeds
- **THEN** `PUID`/`PGID` ownership SHALL be re-applied to the saves tree

### Requirement: Scheduled rollback restarts

When enabled with a non-empty `ROLLBACK_CRON`, the container SHALL stop the server, restore the Backup, and relaunch in-process in the same container (SIGINT, wait `SHUTDOWN_TIMEOUT`, restore, rebuild Game tree and Generated config, new PID; see `server-lifecycle`). Ticks SHALL follow wall-clock minute-level parsing with the `backup-system` non-minute-field rules and a 3600-second fallback; the first tick SHALL be the next trigger after launch. Presence evidence SHALL be ignored and pause gates bypassed: the paused tree is resumed before SIGINT and no quiet-window or save-quiescence wait applies. A combined pending Auto Update download SHALL apply in the same relaunch (see `auto-update`). Every in-process relaunch while rollback is enabled SHALL restore the Backup first, including update-only relaunches with no rollback tick.

#### Scenario: Wall-clock tick restarts the server

- **WHEN** `ROLLBACK_CRON` reaches its next wall-clock trigger with players online
- **THEN** the server SHALL stop, the saves directory SHALL contain exactly the Backup contents, and a new server process SHALL launch with a new PID

#### Scenario: Cron parsing matches backup rules

- **WHEN** `ROLLBACK_CRON` carries non-minute fields or an unparseable expression
- **THEN** non-minute fields SHALL be ignored with a warning and unparseable values SHALL fall back to 3600 seconds

#### Scenario: Players do not delay rollback

- **WHEN** a rollback tick fires while players are connected
- **THEN** the restart SHALL proceed without waiting for the empty-server gate

#### Scenario: Paused tree is resumed for rollback

- **WHEN** a rollback tick fires while the Wine tree is paused
- **THEN** every stopped Wine process SHALL receive SIGCONT before SIGINT and the restore SHALL proceed

#### Scenario: Pending update composes in one restart

- **WHEN** a rollback tick fires while an Auto Update Manifest is downloaded and pending
- **THEN** the same relaunch SHALL restore the rollback Backup and launch from the pending Manifest

#### Scenario: Update-only relaunch still restores

- **WHEN** an Auto Update restart occurs with no rollback tick while rollback is enabled
- **THEN** the relaunch SHALL still restore the rollback Backup before launching from the pending Manifest

### Requirement: Backup suppression

While rollback is enabled, automatic live, cold, and emergency Backups SHALL NOT run; a warning SHALL state that automatic backups are disabled. Manual `backup` and `restore` commands SHALL keep working. No cold or emergency Backup SHALL be taken around a rollback. Lock-held scheduled ticks SHALL wait up to `SHUTDOWN_BACKUP_WAIT` for the lock, then skip the tick with a warning and keep the server running.

#### Scenario: Automatic backups are suppressed

- **WHEN** `ROLLBACK_ENABLED=true` with live, cold, or emergency backups otherwise enabled
- **THEN** no scheduled, shutdown, update-restart, crash, or unexpected-failure Backup SHALL be created and a warning SHALL be logged

#### Scenario: Manual backup still runs

- **WHEN** the operator runs `enshctl backup` while rollback is enabled
- **THEN** a Backup SHALL be created

#### Scenario: Lock-held tick waits then skips

- **WHEN** a scheduled rollback tick fires while a manual backup holds the lock
- **THEN** the tick SHALL wait up to `SHUTDOWN_BACKUP_WAIT` and, if still held, log a warning and keep the server running without restoring

### Requirement: Post-stop failure relaunches

A scheduled restore that fails after the server stopped (corrupt archive, disk full) SHALL log an error naming the file and relaunch the server on the pre-rollback saves, retrying at the next tick. A post-stop lock that is still held after the wait SHALL log an error naming the file and relaunch without restoring. A stop failure that leaves the server alive SHALL exit non-zero without relaunching.

#### Scenario: Failed scheduled restore relaunches old saves

- **WHEN** the server stopped for a scheduled rollback and extraction fails
- **THEN** the server SHALL relaunch on the pre-rollback saves and the next tick SHALL retry

#### Scenario: Stop failure exits without relaunch

- **WHEN** a rollback restart cannot stop the server
- **THEN** the container SHALL exit non-zero and SHALL NOT relaunch

### Requirement: Rollback logging

Rollback state SHALL be logged at INFO through the orchestrator logger: at startup the file, mode, and next run (`on next restart` or a wall-clock countdown such as `in 1h`); before each restore the Backup filename; after each restore the relaunch. Failures SHALL log errors naming the file (see `backup-restore` for the underlying extraction cause).

#### Scenario: Startup summary names the next run

- **WHEN** rollback is enabled with `ROLLBACK_CRON` set
- **THEN** startup SHALL log the file, the schedule, and the wall-clock countdown to the next tick

#### Scenario: Startup-only mode names on-restart

- **WHEN** rollback is enabled without `ROLLBACK_CRON`
- **THEN** startup SHALL log that rollback runs on the next restart

#### Scenario: Pre and post restore lines bracket each rollback

- **WHEN** a rollback restore runs
- **THEN** an INFO line SHALL name the Backup before extraction and an INFO line SHALL confirm the relaunch after success
