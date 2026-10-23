## Purpose

Rebuild of the Game tree as a symlink tree from the Manifest install and Mod overlay on every start.

## Requirements

### Requirement: Game tree rebuild on startup

On every container start, the entrypoint SHALL wipe the Game tree and rebuild it: per-file symlinks to the Manifest install, then Mod overlay symlinks shadowing the same relative paths. Directories SHALL be real directories so the game can create runtime files where needed. When the Manifest install for the resolved Manifest ID is absent, the start SHALL fail with an error naming the missing directory.

#### Scenario: Fresh start symlinks Manifest install

- **WHEN** the container starts with a Manifest install present
- **THEN** every file in the Manifest install SHALL be visible at the same relative path in the Game tree

#### Scenario: Mod overlay shadows Manifest install

- **WHEN** the container starts with files in the mods volume
- **THEN** files present in both Manifest install and Mod overlay SHALL resolve to the mod version in the Game tree

#### Scenario: Removed mod restores original

- **WHEN** a mod is removed and the container restarts
- **THEN** the original file from the Manifest install SHALL be visible again in the Game tree

#### Scenario: Wipe leaves sources untouched

- **WHEN** the container starts
- **THEN** all existing contents of the Game tree SHALL be removed before rebuilding, without deleting source files in the Manifest install, the mods volume, or the config directory

#### Scenario: Missing Manifest install fails start

- **WHEN** the container starts and the Manifest install for the resolved Manifest ID is absent
- **THEN** the entrypoint SHALL fail with an error naming the missing directory

#### Scenario: No shutdown-time tree cleanup

- **WHEN** the container receives SIGTERM
- **THEN** no Game tree cleanup SHALL run; cleanup is implicit in the wipe at the next startup

### Requirement: Config symlink

The game-server path for the server config SHALL be a symlink to the persisted config file. Game writes (e.g. banned players) SHALL persist to the config directory through the symlink and survive restarts.

#### Scenario: First run resolves symlink on generation

- **WHEN** the container starts with no persisted config
- **THEN** the Generated config SHALL be written to the config directory (see `config-management` for merge input) and the Game tree symlink SHALL resolve to it

#### Scenario: Runtime writes to config persist

- **WHEN** the game process writes to the server config at runtime
- **THEN** the write SHALL persist to the config directory and survive container restarts

### Requirement: PERSIST_FILES escape hatch

`PERSIST_FILES` SHALL accept a comma-separated list of relative file paths. Each listed file SHALL be seeded into the config directory from the Manifest install on first run (if not already present) and symlinked from the Game tree to the config directory. Entries that are absolute paths, bare `.`/`..` segments, or contain traversal sequences SHALL be skipped with a warning and create nothing outside the config directory. Entries absent from both Manifest install and Game tree SHALL be skipped. Entries present only in the mods volume SHALL NOT be seeded; the Game tree link SHALL dangle rather than show mod content.

#### Scenario: Default persisted file

- **WHEN** `PERSIST_FILES` is not set
- **THEN** only the server config SHALL be persisted

#### Scenario: Custom persisted file

- **WHEN** `PERSIST_FILES` lists an additional file present in the Manifest install
- **THEN** the file SHALL be seeded into the config directory on first run and symlinked from the Game tree

#### Scenario: Traversal entry skipped

- **WHEN** `PERSIST_FILES` contains an absolute path, a bare `.`/`..`, or a traversal sequence
- **THEN** the entry SHALL be skipped with a warning and no file SHALL be created outside the config directory

### Requirement: Manifest install read-only protection

After a Download, the Manifest install SHALL be marked read-only as defense-in-depth. A process attempting to write to a file symlinked from the Manifest install SHALL fail with a permission error.

#### Scenario: Read-only prevents accidental modification

- **WHEN** a process attempts to write to a file symlinked from the Manifest install
- **THEN** the write SHALL fail with a permission error
