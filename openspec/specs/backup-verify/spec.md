## Purpose

Integrity reporting for stored Backups without extracting them to disk.

## Requirements

### Requirement: Verify Backup integrity

The `verify` invocation SHALL check integrity by streaming each Backup through its decompressor and reading every member to EOF without writing to disk. A Backup that reads completely SHALL be reported as OK; one that fails SHALL be reported as CORRUPT.

#### Scenario: Verify specific Backup

- **WHEN** `verify --file` names an existing Backup
- **THEN** the specified Backup SHALL be streamed to EOF with OK or CORRUPT status reported

#### Scenario: Non-Backup file accepted by presence

- **WHEN** `verify --file` names a grammar-matching or non-grammar file present in a Category directory
- **THEN** that file SHALL be verified (selection by presence is owned by `backup-restore`)

#### Scenario: Unreadable format reported CORRUPT

- **WHEN** `verify --file` names a file whose suffix matches no known compression format
- **THEN** the file SHALL be reported CORRUPT and the command SHALL exit 1

#### Scenario: Unknown filename exits non-zero

- **WHEN** `verify --file` names a Backup that exists in no Category
- **THEN** the command SHALL report the file as not found and exit with a non-zero code

#### Scenario: Verify all Backups

- **WHEN** `verify` or `verify --all` is executed
- **THEN** all Backups in all Categories SHALL be verified

### Requirement: Verify output format

The verify command SHALL output a table (TTY) or plain text (non-TTY) showing each Backup's name, size, and status (OK or CORRUPT).

#### Scenario: Table output on TTY

- **WHEN** verify is executed in a TTY
- **THEN** a table SHALL be displayed with columns for Backup, size, and status

#### Scenario: Plain text output on non-TTY

- **WHEN** verify is executed in a non-TTY (e.g. piped output)
- **THEN** plain text output SHALL be printed without ANSI escape codes

### Requirement: Verify exit code

The verify command SHALL exit with code 0 when every verified Backup is OK, or code 1 when at least one verified Backup is CORRUPT.

#### Scenario: All Backups intact

- **WHEN** all verified Backups stream successfully
- **THEN** exit code SHALL be 0

#### Scenario: Corrupt Backup found

- **WHEN** at least one Backup fails streaming
- **THEN** exit code SHALL be 1 and the corrupt Backup SHALL be listed in the output

### Requirement: Stray files reported as skipped in verify-all

Verify-all SHALL verify every grammar-matching Backup and SHALL report non-grammar files (suffix `.zst`, `.gz`, `.zip`, or `.tar.zst`/`.tar.gz`) present in Category directories as skipped: each skipped filename SHALL be logged at WARNING level, and the command output SHALL include a skipped count. Skipped files SHALL NOT affect the exit code; exit code SHALL remain 0 when all verified Backups are OK and 1 when at least one verified Backup is CORRUPT.

#### Scenario: Stray file skipped with warning

- **WHEN** a Category directory contains one valid Backup and one non-grammar file
- **THEN** the valid Backup SHALL be verified and reported OK/CORRUPT, and the stray SHALL be logged at WARNING as skipped with a skipped count of 1 in the output

#### Scenario: Only stray files present

- **WHEN** Category directories contain only non-grammar files
- **THEN** the command SHALL report zero verified Backups plus the skipped count, and exit code SHALL be 0
