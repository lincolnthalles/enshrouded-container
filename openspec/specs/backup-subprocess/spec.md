## Purpose

Subprocess-isolated backup execution with lowered priority and exclusive file locking.

## Requirements

### Requirement: Backup runs in subprocess

Each backup SHALL execute as a separate `enshctl backup` process rather than in-process. Detached backup processes SHALL run in their own process group; live backups SHALL share the parent's process group. The parent SHALL still wait for each backup process to complete (see `backup-system` for scheduler, shutdown, and crash trigger behavior). Child output SHALL be relayed at a dedicated level between INFO and WARNING with the child's log prefix removed; lock-held skips SHALL stay quiet unless the invocation waited for the lock.

#### Scenario: Scheduler triggers live backup

- **WHEN** the scheduler fires a backup and no other backup holds the lock
- **THEN** a separate backup process SHALL run for the live Category and the scheduler SHALL wait for completion

#### Scenario: Detached backup still awaited

- **WHEN** a detached cold or emergency backup is triggered
- **THEN** a backup process SHALL run in its own process group and the parent SHALL wait for its completion

#### Scenario: Successful backup output is relayed

- **WHEN** the backup process exits with code 0
- **THEN** the parent SHALL relay its output at the dedicated backup level with the child's log prefix removed

#### Scenario: Failed backup output is relayed

- **WHEN** the backup process exits with code 2
- **THEN** the parent SHALL relay its output at the dedicated backup level

#### Scenario: Quiet lock-held skip

- **WHEN** the backup process skips because the lock is held and no wait was requested
- **THEN** the skip SHALL be recorded below warning level

### Requirement: Priority lowering

The backup process SHALL run at the lowest CPU and IO priority so a running backup does not starve the game server. If lowered priority is unavailable, it SHALL warn once per backup run and continue at default priority.

#### Scenario: Warning deduplicated within one run

- **WHEN** CPU and IO priority lowering both fail during one backup run
- **THEN** the first failure SHALL warn once and the second SHALL be recorded below warning level

### Requirement: Backup locking

The backup process SHALL hold an exclusive non-blocking lock on the backup lock file before compressing, so at most one backup process writes at a time, and release it when the backup completes or fails.

#### Scenario: Lock held — skip without changes

- **WHEN** a backup starts and another process holds the lock (and no wait budget remains)
- **THEN** it SHALL exit reporting lock-held and SHALL NOT create, modify, or delete any Backup

#### Scenario: Wait budget expires — warning

- **WHEN** a backup started with a wait budget still cannot acquire the lock after the budget expires
- **THEN** it SHALL exit reporting lock-held and log a warning naming the waited seconds

### Requirement: Backup outcome reporting

The backup process SHALL exit 0 on success, 1 when lock-held, 2 on error. The parent SHALL log a warning naming any unrecognized exit code and its captured output.

#### Scenario: Successful backup reports success

- **WHEN** a backup completes and the lock is released
- **THEN** it SHALL exit with code 0

#### Scenario: Lock held reports lock-held

- **WHEN** a backup skips because the lock is held
- **THEN** it SHALL exit with code 1

#### Scenario: Compression failure leaves no partial backup

- **WHEN** compression fails with a handled archive error while writing a Backup
- **THEN** the partial file SHALL NOT remain, the failure SHALL be logged naming the failed path, and the run SHALL still report success

#### Scenario: Unhandled compression failure cleans partial and reports error

- **WHEN** compression fails with a value error outside handled archive errors
- **THEN** the partial file SHALL NOT remain and the run SHALL exit with code 2

#### Scenario: Error outside compression reports error

- **WHEN** the backup process hits an I/O or value error outside handled archive errors (e.g. the Category directory cannot be created)
- **THEN** the run SHALL exit with code 2

#### Scenario: Spawn failure is logged and skipped

- **WHEN** the backup process cannot be spawned
- **THEN** the parent SHALL log a warning and the backup SHALL be skipped without retry

#### Scenario: Unexpected exit code is logged

- **WHEN** the backup process exits with a code outside 0/1/2
- **THEN** the parent SHALL log a warning naming the exit code and the captured output
