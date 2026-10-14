## Purpose

Time-based retention pruning of backup snapshots across the live, cold, and emergency categories.

## Requirements

### Requirement: Time-based retention cascade

The prune system SHALL apply retention rules from smallest to largest time bucket. Each bucket marks snapshots as "keep"; unmarked snapshots are deleted after all buckets are processed. BACKUP_KEEP_LAST is applied first as a safety floor.

#### Scenario: Retention cascade order

- **WHEN** prune runs with BACKUP_KEEP_LAST=5, BACKUP_KEEP_DAILY=7, BACKUP_KEEP_WEEKLY=4
- **THEN** the 5 newest snapshots SHALL be marked "keep" first, then daily rules mark up to 7 more, then weekly rules mark up to 4 more from the remaining unmarked

#### Scenario: BACKUP_KEEP_LAST as floor

- **WHEN** BACKUP_KEEP_LAST=5 and no time-based rules would keep any snapshots (all BACKUP_KEEP_HOURLY/DAILY/WEEKLY/MONTHLY/YEARLY=0)
- **THEN** the 5 newest snapshots SHALL be retained

#### Scenario: BACKUP_KEEP_LAST=0 disables floor

- **WHEN** BACKUP_KEEP_LAST=0 and at least one time-bucket rule is non-zero
- **THEN** no newest-N floor SHALL apply; only snapshots marked by the time-bucket rules SHALL be retained

### Requirement: Per-category retention

Retention rules SHALL be applied independently to each backup category: live/, cold/, emergency/. Each category is pruned using the same BACKUP_KEEP_* configuration.

#### Scenario: Independent category pruning

- **WHEN** prune runs and live/ has 50 backups while cold/ has 3
- **THEN** retention rules SHALL be applied to live/ and cold/ independently, each producing its own set of kept/deleted backups

### Requirement: BACKUP_KEEP_* bucket semantics

Each BACKUP_KEEP_* variable controls a time bucket:

- `BACKUP_KEEP_HOURLY`: keep the most recent backup per hour, for the last N hours
- `BACKUP_KEEP_DAILY`: keep the most recent backup per calendar day, for the last N days
- `BACKUP_KEEP_WEEKLY`: keep the most recent backup per calendar week (Sunday-start), for the last N weeks
- `BACKUP_KEEP_MONTHLY`: keep the most recent backup per calendar month, for the last N months
- `BACKUP_KEEP_YEARLY`: keep the most recent backup per calendar year, for the last N years

A value of 0 SHALL skip the bucket. A value of -1 on `BACKUP_KEEP_LAST` SHALL keep all snapshots; on a time bucket, -1 SHALL mark the newest snapshot per distinct time key without a bucket-count limit (snapshots sharing a key with an already-marked snapshot are still pruning candidates).

#### Scenario: Daily retention

- **WHEN** BACKUP_KEEP_DAILY=7 and backups exist for each of the last 10 days
- **THEN** the most recent backup from each of the last 7 days SHALL be kept; backups from days 8-10 SHALL be candidates for deletion (unless kept by another rule)

#### Scenario: Weekly retention with Sunday start

- **WHEN** BACKUP_KEEP_WEEKLY=4 and backups span 8 calendar weeks
- **THEN** the most recent backup from each of the last 4 calendar weeks (starting Sunday) SHALL be kept

#### Scenario: Monthly retention

- **WHEN** BACKUP_KEEP_MONTHLY=12 and backups span 18 months
- **THEN** the most recent backup from each of the last 12 calendar months SHALL be kept

#### Scenario: Yearly retention

- **WHEN** BACKUP_KEEP_YEARLY=5 and backups span 8 years
- **THEN** the most recent backup from each of the last 5 calendar years SHALL be kept

#### Scenario: Bucket value -1 keeps all

- **WHEN** BACKUP_KEEP_LAST=-1
- **THEN** all backups SHALL be marked "keep" (no pruning)

#### Scenario: Time-bucket value -1 keeps newest per key

- **WHEN** BACKUP_KEEP_DAILY=-1 and two backups share the same calendar day
- **THEN** the newest backup from each distinct day SHALL be marked "keep"; the older same-day backup SHALL remain a deletion candidate unless kept by another rule

#### Scenario: Bucket value 0 skips

- **WHEN** BACKUP_KEEP_HOURLY=0
- **THEN** the hourly bucket SHALL not mark any backups and SHALL be skipped

### Requirement: Automatic prune after backup

After each successful backup, prune SHALL run automatically on the same category that was just backed up.

#### Scenario: Prune runs after scheduled backup

- **WHEN** a scheduled live backup completes successfully
- **THEN** prune SHALL run on the live/ directory using current BACKUP_KEEP_* settings

#### Scenario: Prune runs after cold backup

- **WHEN** a cold backup completes successfully
- **THEN** prune SHALL run on the cold/ directory

#### Scenario: Prune skipped on backup failure

- **WHEN** a backup fails (lock held, compression error, etc.)
- **THEN** prune SHALL NOT run

### Requirement: Manual prune command

The `prune` subcommand SHALL apply retention rules to all categories on demand. The `--dry-run` flag SHALL show what would be deleted without actually deleting.

#### Scenario: Manual prune

- **WHEN** `enshrouded-server prune` is executed
- **THEN** retention rules SHALL be applied to all categories and matching backups SHALL be deleted

#### Scenario: Dry-run prune

- **WHEN** `enshrouded-server prune --dry-run` is executed
- **THEN** a list of backups that would be deleted SHALL be printed, but no files SHALL be removed

### Requirement: All-zero configuration is a no-op

When all BACKUP_KEEP_* variables are explicitly set to 0, prune SHALL be a no-op as a safety gate. Backups SHALL accumulate until the operator configures retention or runs prune manually. The shipped default is BACKUP_KEEP_LAST=24 with all other buckets 0.

#### Scenario: No pruning when all zero

- **WHEN** all BACKUP_KEEP_* are 0 and prune runs
- **THEN** no backups SHALL be deleted
