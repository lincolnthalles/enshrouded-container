## Purpose

Free-space guards that gate game installs and backups before they run.

## Requirements

### Requirement: Install disk space check

Before downloading game files, the Install SHALL verify that free space plus any partial download of the same Manifest ID meets the configured minimum (default 10 GB). Otherwise the Install SHALL fail with an error naming exact sizes. A startup or CLI Install SHALL exit 1; an Auto Update download failure SHALL follow `auto-update`. Partial data for other Manifest IDs SHALL NOT count.

#### Scenario: Sufficient space for fresh install

- **WHEN** a Manifest ID is requested with no partial download and free space above the minimum
- **THEN** the Install SHALL proceed

#### Scenario: Insufficient space aborts with sizes

- **WHEN** free space plus same-manifest partial data is below the minimum
- **THEN** a startup or CLI Install SHALL fail with an error naming free, partial, and required
  sizes, and exit 1

#### Scenario: Different manifest partial ignored

- **WHEN** partial data belongs to a different Manifest ID
- **THEN** it SHALL NOT count toward the quota

#### Scenario: Custom threshold via env var

- **WHEN** `INSTALL_MIN_FREE_SPACE` sets a custom minimum and free space meets it
- **THEN** the Install SHALL proceed

### Requirement: Backup disk space guard

When free space in the backup directory falls below the stop threshold (default 1 GB), the Backup SHALL be skipped. Below the warn threshold (default 2 GB), a warning SHALL be logged and the Backup SHALL proceed. The guard SHALL apply to every Category.

#### Scenario: Normal backup proceeds

- **WHEN** free space is above the warn threshold and a Backup is triggered
- **THEN** the Backup SHALL proceed without warning

#### Scenario: Warning at low disk

- **WHEN** free space is below the warn threshold
- **THEN** a warning SHALL name the free space and the Backup SHALL proceed

#### Scenario: Skip at critical disk

- **WHEN** free space is below the stop threshold
- **THEN** a warning SHALL be logged and the Backup SHALL be skipped

#### Scenario: Guard applies to all categories

- **WHEN** free space is below the stop threshold
- **THEN** live, cold, and emergency Backups SHALL all be skipped

#### Scenario: Custom thresholds via env vars

- **WHEN** `BACKUP_MIN_FREE_SPACE_WARN` and `BACKUP_MIN_FREE_SPACE_STOP` set custom thresholds
- **THEN** those values SHALL gate Backup execution

### Requirement: Restore disk space check

Before extracting the Backup, the restore SHALL measure free space on the saves filesystem. After extracting to the temporary directory and before clearing saves, the restore SHALL verify that the pre-extraction free space plus the current saves size covers the extracted data. On shortfall, the temporary directory SHALL be cleaned up and the command SHALL exit 1 without modifying saves.

#### Scenario: Sufficient space after extraction

- **WHEN** extraction to tmp succeeds and free space plus saves size covers the extracted data
- **THEN** the restore SHALL proceed to clear saves and move tmp data

#### Scenario: Insufficient space after extraction

- **WHEN** extraction succeeds but free space plus saves size is below the extracted size
- **THEN** the system SHALL log the exact shortfall, clean up tmp, and exit 1 without modifying saves
