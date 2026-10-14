## Purpose

Integrity verification of backup archives without extracting them to disk.

## Requirements

### Requirement: Verify backup integrity

The `verify` subcommand SHALL check archive integrity by streaming each backup through its decompressor and reading every archive member to EOF without writing to disk. A backup that decompresses and reads completely SHALL be reported as OK; one that fails SHALL be reported as CORRUPT.

#### Scenario: Verify specific backup

- **WHEN** `enshrouded-server verify --file enshrouded-20260529-120000.tar.zst` is executed
- **THEN** the specified backup SHALL be decompressed and all members read to EOF, with OK or CORRUPT status reported

#### Scenario: Verify all backups

- **WHEN** `enshrouded-server verify` or `enshrouded-server verify --all` is executed
- **THEN** all backups in all categories (live, cold, emergency) SHALL be verified

### Requirement: Verify output format

The verify command SHALL output a Rich table (TTY) or plain text (non-TTY) showing each backup's path, size, and status (OK or CORRUPT).

#### Scenario: Rich table output on TTY

- **WHEN** verify is executed in a TTY
- **THEN** a Rich table SHALL be displayed with columns: Backup, Size, Status

#### Scenario: Plain text output on non-TTY

- **WHEN** verify is executed in a non-TTY (e.g., piped output)
- **THEN** plain text output SHALL be printed without ANSI escape codes

### Requirement: Verify exit code

The verify command SHALL exit with code 0 if all backups are OK, or code 1 if at least one backup is CORRUPT.

#### Scenario: All backups intact

- **WHEN** all verified backups decompress successfully
- **THEN** exit code SHALL be 0

#### Scenario: Corrupt backup found

- **WHEN** at least one backup fails decompression
- **THEN** exit code SHALL be 1 and the corrupt backup SHALL be listed in the output

### Requirement: Stray archives reported as skipped in verify-all

`verify` without `--file` SHALL verify every archive matching the backup filename grammar and SHALL report non-grammar archive files (suffix `.zst`, `.gz`, `.zip`, or `.tar.zst`/`.tar.gz`) present in category directories as skipped: each skipped filename SHALL be logged at WARNING level, and the command output SHALL include a skipped count. Skipped files SHALL NOT affect the exit code; exit code SHALL remain 0 when all verified archives are OK and 1 when at least one verified archive is CORRUPT.

#### Scenario: Stray archive skipped with warning

- **WHEN** `live/` contains `enshrouded-20260529-120000.tar.zst` (valid) and `manual-copy.zip` (non-grammar)
- **THEN** the valid archive SHALL be verified and reported OK/CORRUPT, and `manual-copy.zip` SHALL be logged at WARNING as skipped with a skipped count of 1 in the output

#### Scenario: Only stray archives present

- **WHEN** category directories contain only non-grammar archives
- **THEN** the command SHALL report zero verified backups plus the skipped count, and exit code SHALL be 0
