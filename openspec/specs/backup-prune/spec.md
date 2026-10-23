## Purpose

Time-based retention pruning of stored Backups across the live, cold, and emergency Categories.

## Requirements

### Requirement: Time-based retention cascade

The prune system SHALL apply retention rules from smallest to largest time bucket. Each bucket marks Backups as "keep"; unmarked Backups are deleted after all buckets are processed. `BACKUP_KEEP_LAST` is applied first as a safety floor.

#### Scenario: Retention cascade order

- **WHEN** prune runs with `BACKUP_KEEP_LAST=5`, daily retention 7, and weekly retention 4
- **THEN** the 5 newest Backups SHALL be marked "keep" first, then daily rules mark up to 7 more (possibly overlapping already-kept), then weekly rules mark up to 4 more from the remaining unmarked

#### Scenario: BACKUP_KEEP_LAST as floor

- **WHEN** `BACKUP_KEEP_LAST=5` and no time-based rules would keep any Backups
- **THEN** the 5 newest Backups SHALL be retained

#### Scenario: BACKUP_KEEP_LAST=0 disables floor

- **WHEN** `BACKUP_KEEP_LAST=0` and at least one time-bucket rule is non-zero
- **THEN** no newest-N floor SHALL apply; only Backups marked by the time-bucket rules SHALL be retained

### Requirement: Per-Category retention

Retention rules SHALL be applied independently to each Backup Category: live, cold, emergency. Each Category is pruned using the same `BACKUP_KEEP_*` configuration.

#### Scenario: Independent Category pruning

- **WHEN** prune runs and live holds many Backups while cold holds few
- **THEN** retention rules SHALL be applied to each Category independently, each producing its own set of kept/deleted Backups

### Requirement: BACKUP_KEEP_* bucket semantics

Each `BACKUP_KEEP_*` variable controls a time bucket: hourly keeps the most recent Backup per hour for the last N hours; daily per calendar day; weekly per Sunday-start week keyed by the week's Sunday date (a week spanning January 1st is one bucket); monthly per calendar month; yearly per calendar year. A value of 0 SHALL skip the bucket. A value of -1 on `BACKUP_KEEP_LAST` SHALL keep all Backups; on a time bucket, -1 SHALL mark the newest Backup per distinct time key without a bucket-count limit (Backups sharing a key with an already-marked Backup are still pruning candidates).

#### Scenario: Daily retention

- **WHEN** daily retention covers the last 7 days and Backups exist for each of the last 10 days
- **THEN** the most recent Backup from each of the last 7 days SHALL be kept; Backups from older days SHALL be candidates for deletion (unless kept by another rule)

#### Scenario: Weekly retention with Sunday start

- **WHEN** weekly retention covers the last 4 weeks and Backups span 8 calendar weeks
- **THEN** the most recent Backup from each of the last 4 Sunday-start weeks SHALL be kept, where a week spanning January 1st counts once under its Sunday's date

#### Scenario: Monthly retention

- **WHEN** monthly retention covers the last 12 months and Backups span 18 months
- **THEN** the most recent Backup from each of the last 12 calendar months SHALL be kept

#### Scenario: Yearly retention

- **WHEN** yearly retention covers the last 5 years and Backups span 8 years
- **THEN** the most recent Backup from each of the last 5 calendar years SHALL be kept

#### Scenario: Bucket value -1 keeps all

- **WHEN** `BACKUP_KEEP_LAST=-1`
- **THEN** all Backups SHALL be marked "keep" (no pruning)

#### Scenario: Time-bucket value -1 keeps newest per key

- **WHEN** daily retention is -1 and two Backups share the same calendar day
- **THEN** the newest Backup from each distinct day SHALL be marked "keep"; the older same-day Backup SHALL remain a deletion candidate unless kept by another rule

#### Scenario: Bucket value 0 skips

- **WHEN** hourly retention is 0
- **THEN** the hourly bucket SHALL not mark any Backups and SHALL be skipped

### Requirement: Automatic prune after Backup

After each successful Backup, prune SHALL run automatically on the same Category that was just backed up. A Backup that fails, is skipped, or stops early for low disk space SHALL NOT trigger pruning.

#### Scenario: Prune runs after scheduled Backup

- **WHEN** a scheduled live Backup completes successfully
- **THEN** prune SHALL run on the live Category using current `BACKUP_KEEP_*` settings

#### Scenario: Prune runs after cold Backup

- **WHEN** a cold Backup completes successfully
- **THEN** prune SHALL run on the cold Category

#### Scenario: Prune skipped on Backup failure

- **WHEN** a Backup fails, is skipped, or stops early for low disk space
- **THEN** prune SHALL NOT run

### Requirement: Manual prune command

The `prune` invocation SHALL apply retention rules to all Categories on demand and log the retention configuration. The `--dry-run` flag SHALL show what would be deleted without actually deleting.

#### Scenario: Manual prune

- **WHEN** `prune` is executed
- **THEN** retention rules SHALL be applied to all Categories and matching Backups SHALL be deleted

#### Scenario: Dry-run prune

- **WHEN** `prune --dry-run` is executed
- **THEN** a list of Backups that would be deleted SHALL be printed, but no files SHALL be removed

### Requirement: All-zero configuration is a no-op

When all `BACKUP_KEEP_*` variables are explicitly set to 0, prune SHALL be a no-op as a safety gate, including manual prune runs. The shipped default keeps the newest 24 Backups with all other buckets 0.

#### Scenario: No pruning when all zero

- **WHEN** all `BACKUP_KEEP_*` are 0 and prune runs
- **THEN** no Backups SHALL be deleted
