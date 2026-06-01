## Requirements

### Requirement: Process tree CPU and memory monitoring

The system SHALL provide functions to read CPU ticks and memory (RSS) from `/proc` for a given PID and all its descendants. These functions SHALL be in `enshctl.resources`.

#### Scenario: Read RSS for a process

- **WHEN** `read_pid_rss(pid)` is called for a running process
- **THEN** it SHALL return the VmRSS in kB from `/proc/[pid]/status`

#### Scenario: Read CPU ticks for a process

- **WHEN** `read_pid_cpu_ticks(pid)` is called for a running process
- **THEN** it SHALL return the sum of utime+stime+cutime+cstime from `/proc/[pid]/stat`

#### Scenario: Collect all child PIDs recursively

- **WHEN** `get_all_child_pids(parent_pid)` is called
- **THEN** it SHALL return a list of all descendant PIDs by reading `/proc/[pid]/task/[pid]/children`

#### Scenario: Read system CPU ticks

- **WHEN** `read_system_cpu_ticks()` is called
- **THEN** it SHALL return the total CPU ticks from the first line of `/proc/stat`

### Requirement: Resource poller thread

The system SHALL provide a `start_resource_poller(server_pid, stop_event, settings)` function that spawns a daemon thread logging CPU and memory usage for both `enshctl` and the game server process tree at a configurable interval.

#### Scenario: Poller logs resource usage

- **WHEN** the resource poller thread is running and the interval elapses
- **THEN** it SHALL log `enshctl: X.X% CPU, Y MB RSS | enshrouded_server.exe: X.X% CPU, Y MB RSS (N procs)`

#### Scenario: Poller respects stop event

- **WHEN** `stop_event` is set
- **THEN** the poller thread SHALL exit

#### Scenario: Poller disabled when interval is zero

- **WHEN** `RESOURCE_POLL_INTERVAL=0` is set
- **THEN** `start_resource_poller` SHALL return `None` and not spawn a thread
