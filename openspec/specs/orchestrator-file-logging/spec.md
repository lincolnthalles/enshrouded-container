## Purpose

Opt-in orchestrator file logging with game server output filtered out.

## Requirements

### Requirement: Orchestrator file logging

When `ORCHESTRATOR_LOG_ENABLED` is true, orchestrator logs at or above `ORCHESTRATOR_LOG_LEVEL`
(default `WARNING`) SHALL be written to `ORCHESTRATOR_LOG_FILE` (default
`/data/logs/orchestrator.log`) in the same format as the console, with game server output excluded.
The log file SHALL rotate at 5 MB keeping one backup. The parent directory SHALL be created
automatically. The backup child process SHALL NOT write to the file directly (its output reaches the
file only via the parent relay when admitted by the level). When `ORCHESTRATOR_LOG_ENABLED` is false
or unset, no file output SHALL be added and behavior SHALL be unchanged.

#### Scenario: File logging enabled

- **WHEN** `ORCHESTRATOR_LOG_ENABLED=true` and the container starts
- **THEN** orchestrator logs at or above `ORCHESTRATOR_LOG_LEVEL` SHALL be written to `ORCHESTRATOR_LOG_FILE`, excluding game server output

#### Scenario: Default log file path

- **WHEN** `ORCHESTRATOR_LOG_ENABLED=true` and `ORCHESTRATOR_LOG_FILE` is unset
- **THEN** the log file SHALL be `/data/logs/orchestrator.log`

#### Scenario: Custom log file path

- **WHEN** `ORCHESTRATOR_LOG_ENABLED=true` and `ORCHESTRATOR_LOG_FILE` names another path
- **THEN** the log file SHALL be written at that path

#### Scenario: File logging filters below level

- **WHEN** `ORCHESTRATOR_LOG_LEVEL` is at its default and the orchestrator emits INFO records
- **THEN** those records SHALL appear on the console but NOT in the log file

#### Scenario: File logging disabled by default

- **WHEN** `ORCHESTRATOR_LOG_ENABLED` is false or unset
- **THEN** no file output SHALL be added and behavior SHALL be unchanged

#### Scenario: Missing file path fails fast

- **WHEN** `ORCHESTRATOR_LOG_ENABLED=true` and `ORCHESTRATOR_LOG_FILE` is explicitly empty
- **THEN** the entrypoint SHALL exit non-zero with an error naming `ORCHESTRATOR_LOG_FILE`

#### Scenario: Log rotation at 5 MB

- **WHEN** the log file reaches 5 MB
- **THEN** the file SHALL be rotated keeping one backup and a new file SHALL be created

#### Scenario: Game server output excluded

- **WHEN** the game server writes to stdout or its log file is tailed
- **THEN** those entries SHALL NOT appear in the orchestrator log file

#### Scenario: Parent directory created

- **WHEN** file logging is enabled and the configured file's parent directory does not exist
- **THEN** the directory SHALL be created automatically
