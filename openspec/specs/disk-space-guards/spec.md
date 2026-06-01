## Requirements

### Requirement: Install disk space check

Before downloading game files, the system SHALL compute `effective_free = shutil.disk_usage(MANIFESTS_DIR).free + size(partial_download_dir)` and compare against `INSTALL_MIN_FREE_SPACE` (default 10 GB, configurable via env var). If `effective_free < INSTALL_MIN_FREE_SPACE`, the system SHALL log an error with exact sizes and exit with code 1.

#### Scenario: Sufficient space for fresh install

- **WHEN** `VERSION=1234567890123456789` is set, no partial download exists, and free space is 12 GB
- **THEN** the install SHALL proceed (12 GB ≥ 10 GB threshold)

#### Scenario: Insufficient space for fresh install

- **WHEN** `VERSION=1234567890123456789` is set, no partial download exists, and free space is 8 GB
- **THEN** the system SHALL log "Insufficient disk space" with the shortfall amount and exit with code 1

#### Scenario: Partial download counts toward quota

- **WHEN** `VERSION=1234567890123456789` is set, a 3 GB partial download exists for the same manifest, and free space is 7 GB
- **THEN** `effective_free` SHALL be 10 GB (7 + 3) and the install SHALL proceed

#### Scenario: Different manifest ignores partial

- **WHEN** `VERSION=9999999999999999999` is set, a 3 GB partial download exists for a different manifest, and free space is 7 GB
- **THEN** `effective_free` SHALL be 7 GB (partial is for a different manifest) and the system SHALL abort

#### Scenario: Custom threshold via env var

- **WHEN** `INSTALL_MIN_FREE_SPACE=5368709120` (5 GB) is set and free space is 6 GB
- **THEN** the install SHALL proceed (6 GB ≥ 5 GB threshold)

### Requirement: Backup disk space guard

The system SHALL check `shutil.disk_usage(backup_dir).free` at the start of `create_backup()`. If free space is below `BACKUP_MIN_FREE_SPACE_STOP` (default 1 GB), the backup SHALL be skipped and `None` returned. If free space is below `BACKUP_MIN_FREE_SPACE_WARN` (default 2 GB), a warning SHALL be logged and the backup SHALL proceed.

#### Scenario: Normal backup proceeds

- **WHEN** free space is 5 GB and a backup is triggered
- **THEN** the backup SHALL proceed without warning

#### Scenario: Warning at low disk

- **WHEN** free space is 1.5 GB (below 2 GB warn threshold) and a backup is triggered
- **THEN** a warning SHALL be logged ("Disk space low: 1.5 GB free") and the backup SHALL proceed

#### Scenario: Skip at critical disk

- **WHEN** free space is 0.8 GB (below 1 GB stop threshold) and a backup is triggered
- **THEN** a warning SHALL be logged ("Disk space critical: 0.8 GB free, skipping backup") and `create_backup()` SHALL return `None`

#### Scenario: Guard applies to all categories

- **WHEN** free space is below the stop threshold
- **THEN** live, cold, and emergency backups SHALL all be skipped

#### Scenario: Custom thresholds via env vars

- **WHEN** `BACKUP_MIN_FREE_SPACE_WARN=1073741824` and `BACKUP_MIN_FREE_SPACE_STOP=536870912` are set
- **THEN** the warn threshold SHALL be 1 GB and the stop threshold SHALL be 512 MB

### Requirement: Restore disk space check

After extracting the backup to a temporary directory and before clearing saves, the system SHALL verify that `shutil.disk_usage(SAVE_DIR).free + du(SAVE_DIR) >= du(tmp_dir)`. If this check fails, the system SHALL log an error with exact sizes (extracted data, current saves, free space, shortfall) and clean up the temporary directory without modifying saves.

#### Scenario: Sufficient space after extraction

- **WHEN** extraction to tmp succeeds and `free + du(saves) >= du(tmp)`
- **THEN** the restore SHALL proceed to clear saves and move tmp data

#### Scenario: Insufficient space after extraction

- **WHEN** extraction to tmp succeeds but `free + du(saves) < du(tmp)`
- **THEN** the system SHALL log the exact shortfall, clean up tmp, and exit with code 1 without modifying saves

#### Scenario: Extraction fails from ENOSPC

- **WHEN** extraction to tmp fails because the disk fills mid-write
- **THEN** the system SHALL clean up tmp, log the error with current free space, and exit with code 1 without modifying saves
