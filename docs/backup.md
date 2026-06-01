# Backup system

The orchestrator backs up `/data/saves/` as compressed archives. Backups run as separate subprocesses with lowered CPU/IO priority and file locking preventing concurrent runs.

## Categories

| Category    | Trigger                                        | Dir          |
| ----------- | ---------------------------------------------- | ------------ |
| `live`      | Scheduler (first run immediate, then per cron) | `live/`      |
| `cold`      | Graceful shutdown (SIGTERM)                    | `cold/`      |
| `emergency` | Unexpected server exit                         | `emergency/` |

Files are named `enshrouded-YYYYMMDD-HHMMSS[-cold|-emergency].<ext>`.

## Formats & Compression

| Format | Extension  | Levels | Default |
| ------ | ---------- | ------ | ------- |
| `zstd` | `.tar.zst` | 1-22   | 9       |
| `gzip` | `.tar.gz`  | 1-9    | 6       |
| `zip`  | `.zip`     | 0-9    | 6       |

## Retention

Restic-inspired retention applied per category independently. Controlled by `BACKUP_KEEP_*` env vars.

| Value | Meaning                                                                    |
| ----- | -------------------------------------------------------------------------- |
| `-1`  | Keep all                                                                   |
| `0`   | Don't limit via this rule (default for hourly/daily/weekly/monthly/yearly) |
| `>0`  | Keep at most N backups in this bucket                                      |

When ALL `BACKUP_KEEP_*` are `0`, pruning is skipped entirely — nothing is deleted.

## Subcommands

| Command   | Description                                                        |
| --------- | ------------------------------------------------------------------ |
| `backup`  | Run a manual backup now (`--cold`, `--emergency` flags)            |
| `restore` | Interactive TUI restore (or `--file`/`--when` for non-interactive) |
| `prune`   | Enforce retention rules (`--dry-run` supported)                    |
| `verify`  | Check archive integrity (`--file` or `--all`)                      |

## Configuration

### Enable/disable

| Env var            | Default | Description                                |
| ------------------ | ------- | ------------------------------------------ |
| `BACKUP_LIVE`      | `1`     | Enable scheduled live backups              |
| `BACKUP_COLD`      | `1`     | Enable cold backup on graceful shutdown    |
| `BACKUP_EMERGENCY` | `1`     | Enable emergency backup on unexpected exit |

Boolean values: `1`/`true`/`on`/`yes` = enabled, `0`/`false`/`off`/`no` = disabled (case-insensitive).

### Scheduling

| Env var       | Default        | Description                              |
| ------------- | -------------- | ---------------------------------------- |
| `BACKUP_CRON` | `*/60 * * * *` | Cron expression for live backup interval |

### Format & compression

| Env var         | Default         | Description                                             |
| --------------- | --------------- | ------------------------------------------------------- |
| `BACKUP_FORMAT` | `zstd`          | Compression format (`zstd`, `gzip`, `zip`)              |
| `BACKUP_LEVEL`  | format default  | Override compression level (9 for zstd, 6 for gzip/zip) |
| `BACKUP_DIR`    | `/data/backups` | Backup storage directory                                |

### Disk space guards

| Env var                      | Default             | Description                               |
| ---------------------------- | ------------------- | ----------------------------------------- |
| `BACKUP_MIN_FREE_SPACE_WARN` | `2147483648` (2 GB) | Log warning below this threshold, proceed |
| `BACKUP_MIN_FREE_SPACE_STOP` | `1073741824` (1 GB) | Skip backup below this threshold          |

### Retention policy

| Env var               | Default | Description                             |
| --------------------- | ------- | --------------------------------------- |
| `BACKUP_KEEP_LAST`    | `24`    | Keep N most recent backups (`-1` = all) |
| `BACKUP_KEEP_HOURLY`  | `0`     | Keep N most recent hourly buckets       |
| `BACKUP_KEEP_DAILY`   | `0`     | Keep N most recent daily buckets        |
| `BACKUP_KEEP_WEEKLY`  | `0`     | Keep N most recent weekly buckets       |
| `BACKUP_KEEP_MONTHLY` | `0`     | Keep N most recent monthly buckets      |
| `BACKUP_KEEP_YEARLY`  | `0`     | Keep N most recent yearly buckets       |

## How it works

1. The main process spawns `enshctl backup` as a subprocess (not in-process thread)
2. The child acquires `flock(LOCK_EX | LOCK_NB)` on `.lock` in the backup dir — prevents concurrent backups
3. CPU priority is lowered via `os.nice(19)` and IO via `ionice -c3` (if `CAP_SYS_NICE` available)
4. Free space is checked against `BACKUP_MIN_FREE_SPACE_STOP`; backup skips if below
5. Saves are compressed to a timestamped file in the category subdirectory
6. Retention pruning runs after each backup, governed by `BACKUP_KEEP_*` rules
7. The parent relays child output to stdout (console at `[BACKUP]` level; file log at `WARNING` level)

## Exit codes

| Code | Meaning                                      |
| ---- | -------------------------------------------- |
| 0    | Success                                      |
| 1    | Lock held by another process (skip)          |
| 2    | Error (compression failure, disk full, etc.) |
