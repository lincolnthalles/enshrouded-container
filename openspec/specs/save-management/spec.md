## Purpose

Persistent world save data volume and its wiring into the Generated config.

## Requirements

### Requirement: Saved games volume

The container SHALL expose the saves directory as a volume for persistent world save data. Default location `/data/saves` (see `shared-config` for default locations). The Generated config's save directory field SHALL be an absolute path defaulting to the saves volume. Relative values from any source (Base config, env var override) SHALL be remapped to the volume default with a warning naming the discarded value, since the game resolves them against the ephemeral Game tree.

#### Scenario: Save directory is configured

- **WHEN** the config is generated with no save directory configured
- **THEN** the save directory field SHALL be set to the saves volume path

#### Scenario: Relative save directory remapped

- **WHEN** the Base config or env override provides a relative save path
- **THEN** the save directory field SHALL be the saves volume path and a warning SHALL name the discarded value

#### Scenario: Empty save directory falls back silently

- **WHEN** the Base config or env override provides an empty or whitespace-only save path
- **THEN** the save directory field SHALL be the saves volume path with no warning

#### Scenario: Absolute save directory preserved

- **WHEN** an env override provides an absolute, non-protected save path
- **THEN** the save directory field SHALL be that absolute path with no warning

#### Scenario: Save directory is writable

- **WHEN** the game server starts
- **THEN** the server SHALL be able to write save files to the saves volume

#### Scenario: Save directory persists across restarts

- **WHEN** the container is stopped and restarted with the same volume
- **THEN** previously saved world data SHALL still be present in the saves volume

### Requirement: Save directory consumers

Backup and Restore SHALL target the save directory from the Generated config, defaulting to the saves volume. The configured save directory SHALL exist before the server starts. Startup SHALL attempt to apply `PUID`/`PGID` ownership and warn once if it cannot.

#### Scenario: Backup and Restore follow configured saves

- **WHEN** the Generated config's save directory is an absolute path outside `/data`
- **THEN** Backups SHALL read that directory and Restores SHALL write to it

#### Scenario: Configured save directory prepared at start

- **WHEN** the Generated config selects a save directory that does not exist
- **THEN** startup SHALL create it and attempt to apply the configured ownership before launching the server

#### Scenario: Ownership failure warns and continues

- **WHEN** startup cannot apply the configured ownership to the save directory
- **THEN** it SHALL log a warning and continue starting the server

### Requirement: Generated save directory resolution

A missing, empty, or unreadable Generated config SHALL fall back to the saves volume. A relative, malformed, non-string, NUL-containing, or protected-path save directory SHALL fall back to the saves volume with a warning. The configured path SHALL be canonicalized before overlap checks, so traversal and symlink aliases cannot target protected paths. Protected paths are the filesystem root and the backups, config, manifests, logs, mods, and wine prefix locations.

#### Scenario: Missing Generated config defaults to volume

- **WHEN** Backup or Restore runs without a readable Generated config
- **THEN** the saves volume SHALL be used

#### Scenario: Unsafe save directory falls back

- **WHEN** the Generated config's save directory is the filesystem root or resolves onto a protected path
- **THEN** the saves volume SHALL be used with a warning

### Requirement: Log directory

The container SHALL set the Generated config's log directory field to an absolute path defaulting to the logs volume. Relative values SHALL be remapped to the logs volume with a warning, mirroring the save directory rule. The game writes identical content to its log file and to stdout; the orchestrator relays stdout to the console, so no log-file symlinking or tailing is required for Docker log collection.

#### Scenario: Log directory is configured

- **WHEN** the config is generated with no log directory configured
- **THEN** the log directory field SHALL be set to the logs volume path

#### Scenario: Relative log directory remapped

- **WHEN** the Base config or env override provides a relative log path
- **THEN** the log directory field SHALL be the logs volume path and a warning SHALL name the discarded value

#### Scenario: Logs are visible in docker logs

- **WHEN** the server runs
- **THEN** `docker logs` SHALL display the server output via the orchestrator's stdout relay, without any log-file symlink or tail process

### Requirement: Auto Pause save-signature consumption

Auto Pause SHALL read the newest top-level `*.ksd` file's path, size, and modification time from the
same resolved save directory used by Backup and Restore. It SHALL NOT write, rename, delete, or
restore save files. The pause decision that consumes the signature SHALL follow `auto-pause`.

#### Scenario: Newest save is tracked

- **WHEN** the save directory contains multiple top-level `*.ksd` files
- **THEN** Auto Pause SHALL read the newest one by modification time
- **AND** it SHALL read that file's size and modification time without writing it

#### Scenario: Custom save directory is followed

- **WHEN** the Generated config names an absolute save directory outside `/data`
- **THEN** Auto Pause SHALL read `*.ksd` files from that directory
- **AND** it SHALL NOT fall back to the volume default
