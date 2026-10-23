## Purpose

Opt-in orchestrator file logging with game server output filtered out.

## Requirements

### Requirement: Orchestrator file logging

When a log file path is configured, orchestrator logs at or above the configured file log level (default WARNING) SHALL be written there in the same format as the console, with game server output excluded. The log file SHALL rotate at 5 MB keeping one backup. The parent directory SHALL be created automatically. A value of `true` SHALL resolve to `/data/logs/orchestrator.log`. The backup child process SHALL NOT write to the file directly (its output reaches the file only via the parent relay when admitted by the level). Without configuration, behavior SHALL be unchanged.

#### Scenario: File logging enabled

- **WHEN** a log file path is configured and the container starts
- **THEN** orchestrator logs at or above the file log level SHALL be written there, excluding game server output

#### Scenario: File logging filters below level

- **WHEN** the file log level is at its default and the orchestrator emits INFO records
- **THEN** those records SHALL appear on the console but NOT in the log file

#### Scenario: File logging disabled by default

- **WHEN** no log file is configured
- **THEN** no file output SHALL be added and behavior SHALL be unchanged

#### Scenario: Log rotation at 5 MB

- **WHEN** the log file reaches 5 MB
- **THEN** the file SHALL be rotated keeping one backup and a new file SHALL be created

#### Scenario: Game server output excluded

- **WHEN** the game server writes to stdout or its log file is tailed
- **THEN** those entries SHALL NOT appear in the orchestrator log file

#### Scenario: Parent directory created

- **WHEN** a log file path is configured and its parent directory does not exist
- **THEN** the directory SHALL be created automatically

#### Scenario: True resolves to default path

- **WHEN** the log file setting is `true`
- **THEN** orchestrator logs SHALL be written to `/data/logs/orchestrator.log`
