## Purpose

CPU and memory monitoring of the server process tree via /proc.

## Requirements

### Requirement: Process tree CPU and memory monitoring

The system SHALL report CPU share and memory (RSS) for a process and all its descendants, read from `/proc`. Unreadable processes SHALL contribute zero rather than failing the report.

#### Scenario: Dead process contributes zero

- **WHEN** a monitored process exits mid-poll
- **THEN** its contribution SHALL be zero and the report SHALL still be logged

### Requirement: Resource poller thread

While the server runs, a daemon poller thread SHALL log CPU and memory usage for both the orchestrator and the game server process tree at a configurable interval (default 60s). A non-positive interval SHALL disable polling. The poller SHALL stop when shutdown begins.

#### Scenario: Poller logs resource usage

- **WHEN** the resource poller is running and the interval elapses
- **THEN** a line SHALL be logged with orchestrator CPU/RSS and game server CPU/RSS with process count

#### Scenario: Poller respects stop event

- **WHEN** shutdown begins
- **THEN** no further resource-usage lines SHALL be logged

#### Scenario: Poller disabled when interval is zero

- **WHEN** the poll interval is set to 0
- **THEN** no periodic resource-usage lines SHALL be logged
