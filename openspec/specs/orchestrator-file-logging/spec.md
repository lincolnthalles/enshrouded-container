## Requirements

### Requirement: Orchestrator file logging

When `ORCHESTRATOR_LOG_FILE` is set, the system SHALL add a `RotatingFileHandler` to the root logger with `maxBytes=5242880` (5 MB) and `backupCount=1`. The handler SHALL use the same format as the console handler (`%(asctime)s [%(levelname)s] %(message)s`). The handler SHALL filter out entries where `record.source == 'gameserver'`.

#### Scenario: File logging enabled

- **WHEN** `ORCHESTRATOR_LOG_FILE=/logs/orchestrator.log` is set and the container starts
- **THEN** orchestrator logs SHALL be written to `/logs/orchestrator.log`, excluding game server output

#### Scenario: File logging disabled by default

- **WHEN** `ORCHESTRATOR_LOG_FILE` is not set
- **THEN** no file handler SHALL be added and behavior SHALL be unchanged

#### Scenario: Log rotation at 5 MB

- **WHEN** the log file reaches 5 MB
- **THEN** the file SHALL be rotated to `orchestrator.log.1` and a new `orchestrator.log` SHALL be created

#### Scenario: Game server output excluded

- **WHEN** the game server writes to stdout (via `_stream_output` or `_tail_log_file`)
- **THEN** those entries SHALL NOT appear in the orchestrator log file

#### Scenario: Parent directory created

- **WHEN** `ORCHESTRATOR_LOG_FILE=/logs/orchestrator.log` is set and `/logs/` does not exist
- **THEN** the directory SHALL be created automatically

### Requirement: Game server log entries tagged

All game server log calls (`_stream_output` and `_tail_log_file` in `start.py`) SHALL include `extra={'source': 'gameserver'}` so that filters can identify and exclude them.

#### Scenario: Stream output tagged

- **WHEN** `_stream_output` logs a line from the server process
- **THEN** the log record SHALL have `source='gameserver'`

#### Scenario: Log tail tagged

- **WHEN** `_tail_log_file` relays a line from the game log
- **THEN** the log record SHALL have `source='gameserver'`
