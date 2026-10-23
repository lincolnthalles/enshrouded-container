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

- **WHEN** an env override provides an absolute save path
- **THEN** the save directory field SHALL be that absolute path with no warning

#### Scenario: Save directory is writable

- **WHEN** the game server starts
- **THEN** the server SHALL be able to write save files to the saves volume

#### Scenario: Save directory persists across restarts

- **WHEN** the container is stopped and restarted with the same volume
- **THEN** previously saved world data SHALL still be present in the saves volume

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
