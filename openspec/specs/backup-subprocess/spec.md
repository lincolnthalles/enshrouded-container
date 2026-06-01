## Requirements

### Requirement: Backup runs in subprocess

Each backup invocation SHALL execute as a separate subprocess (`enshctl backup ...`) rather than in-process. The subprocess SHALL be spawned via `subprocess.run(capture_output=True)` using a unified `_run_backup(extra_args: list[str] | None = None)` function. On non-zero exit (except lock-held), the captured stdout and stderr SHALL be logged at WARNING level.

#### Scenario: Scheduler spawns subprocess

- **WHEN** the cron scheduler fires a backup
- **THEN** it SHALL call `_run_backup()` which spawns `subprocess.run(["enshctl", "backup"], capture_output=True)` and wait for completion

#### Scenario: Shutdown handler spawns subprocess

- **WHEN** the SIGTERM handler triggers a cold backup
- **THEN** it SHALL call `_run_backup(["--cold"])` which spawns `subprocess.run(["enshctl", "backup", "--cold"], capture_output=True)` and wait for completion

#### Scenario: Crash handler spawns subprocess

- **WHEN** the server exits unexpectedly and a backup is triggered
- **THEN** it SHALL call `_run_backup(["--emergency"])` which spawns `subprocess.run(["enshctl", "backup", "--emergency"], capture_output=True)` and wait for completion

#### Scenario: Child errors surface to parent

- **WHEN** the backup subprocess exits with code 2
- **THEN** the parent SHALL log the captured output at WARNING level (e.g., "Backup failed (exit 2): <output>")

#### Scenario: Successful backup stays quiet

- **WHEN** the backup subprocess exits with code 0
- **THEN** the parent SHALL log at INFO level without dumping child output

### Requirement: Priority lowering

The `backup_runner` SHALL lower CPU priority via `os.nice(19)` and IO priority via `ionice -c3`. If `SYS_NICE` capability is unavailable, it SHALL log a warning once and continue. The `_lower_priority` function SHALL use closure state (via `_make_priority_lowerer()`) instead of a `global` variable for the "warned once" flag.

#### Scenario: Priority lowered successfully

- **WHEN** `backup_runner.main()` is called with `SYS_NICE` capability available
- **THEN** the process SHALL run at nice 19 and ionice class 3

#### Scenario: Warning logged once on failure

- **WHEN** `os.nice(19)` raises `OSError` on first call
- **THEN** a warning SHALL be logged at WARNING level
- **WHEN** `os.nice(19)` raises `OSError` on second call
- **THEN** the message SHALL be logged at DEBUG level (no duplicate warning)

### Requirement: Backup file locking

The backup subprocess SHALL acquire an exclusive non-blocking lock on `/data/backups/.lock` using `fcntl.flock(fd, LOCK_EX | LOCK_NB)` before compressing. The lock SHALL be released after compression completes. The lock functions SHALL be defined in `enshctl/backup/locking.py` and re-exported from `enshctl/backup`.

#### Scenario: Lock acquired successfully

- **WHEN** the backup subprocess starts and no other process holds the lock
- **THEN** the lock SHALL be acquired and backup SHALL proceed

#### Scenario: Lock held — auto backup skips

- **WHEN** the backup subprocess is spawned by the scheduler and the lock is held by another process
- **THEN** the subprocess SHALL exit with code 1 and the scheduler SHALL skip this backup cycle silently

#### Scenario: Lock held — manual backup fails

- **WHEN** the backup subprocess is spawned by a manual `enshctl backup` command and the lock is held
- **THEN** the subprocess SHALL exit with code 1 and an error message SHALL be displayed to the user

#### Scenario: Lock released on process exit

- **WHEN** the backup subprocess exits (success or failure)
- **THEN** the lock SHALL be released automatically (fcntl.flock releases on fd close)

### Requirement: Backup subprocess runner

The `backup_runner.main()` function SHALL return an integer exit code (`0` for success, `1` for lock held, `2` for error) instead of calling `sys.exit()`. The `commands/backup.py` wrapper SHALL call `sys.exit()` with the returned code. The exit code constants (`EXIT_SUCCESS`, `EXIT_LOCK_HELD`, `EXIT_ERROR`) SHALL be preserved.

#### Scenario: Successful backup returns 0

- **WHEN** `backup_runner.main()` completes a backup successfully
- **THEN** it SHALL return `0`

#### Scenario: Lock held returns 1

- **WHEN** `backup_runner.main()` cannot acquire the lock
- **THEN** it SHALL return `1`

#### Scenario: Error returns 2

- **WHEN** `backup_runner.main()` encounters an OSError during backup
- **THEN** it SHALL return `2`

#### Scenario: commands/backup.py handles exit

- **WHEN** `commands/backup.py:run()` calls `backup_runner.main()`
- **THEN** it SHALL call `sys.exit()` with the returned exit code
