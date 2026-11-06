## Purpose

CPU and memory monitoring of the server process tree via /proc.

## Requirements

### Requirement: Process tree CPU and memory monitoring

The system SHALL report CPU share and memory (RSS) for a process and all its descendants, read from `/proc`. Unreadable processes SHALL contribute zero rather than failing the report.

#### Scenario: Dead process contributes zero

- **WHEN** a monitored process exits mid-poll
- **THEN** its contribution SHALL be zero and the report SHALL still be logged

### Requirement: Resource poller thread

While the server runs, a daemon poller thread SHALL log CPU and memory usage for both the orchestrator and the game server process tree at a configurable interval (default 60s). A non-positive interval SHALL disable polling. The poller SHALL stop when shutdown begins. When polling is enabled and Auto Pause holds a quiet window (see `auto-pause`), a poll due while the window is held SHALL be skipped, and the poller SHALL log `Resource polling suspended by Auto Pause` at INFO. The suspension line SHALL be logged once per quiet window; additional due polls during the same window SHALL NOT log again. After the window ends, the poller SHALL log `Resource polling resumed` at INFO and resume one full polling interval later.

#### Scenario: Poller logs resource usage

- **WHEN** the resource poller is running and the interval elapses
- **THEN** a line SHALL be logged with orchestrator CPU/RSS and game server CPU/RSS with process count

#### Scenario: Poller respects stop event

- **WHEN** shutdown begins
- **THEN** no further resource-usage lines SHALL be logged

#### Scenario: Poller disabled when interval is zero

- **WHEN** the poll interval is set to 0
- **THEN** no periodic resource-usage lines SHALL be logged
- **AND** no polling suspension or resume line SHALL be logged

#### Scenario: Polling suspends while paused

- **WHEN** a poll is due while Auto Pause holds a quiet window with polling enabled
- **THEN** `Resource polling suspended by Auto Pause` SHALL be logged at INFO
- **AND** no resource-usage line SHALL be logged while the window remains held
- **AND** `Resource polling resumed` SHALL be logged at INFO after the window ends
- **AND** resource-usage lines SHALL resume one full interval after the window ends

#### Scenario: Polling resumes after an aborted pause attempt

- **WHEN** a poll is waiting while a quiet window ends because the pause attempt aborts before suspension
- **THEN** `Resource polling resumed` SHALL be logged at INFO
- **AND** resource-usage lines SHALL resume one full interval later
