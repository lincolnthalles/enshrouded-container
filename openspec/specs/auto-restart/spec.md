# auto-restart Specification

## Purpose

Reset the running world on a wall-clock or elapsed schedule by restarting the server in-process,
without changing the Active Manifest, while giving connected players a bounded grace window.

## Requirements

### Requirement: Auto Restart enablement

Auto Restart SHALL be opt-in via `AUTO_RESTART_ENABLED` (default false). An invalid boolean value
SHALL use the default of false. When disabled, no automatic restart SHALL run.

#### Scenario: Disabled by default

- **WHEN** no Auto Restart setting is provided
- **THEN** no automatic restart SHALL occur

#### Scenario: Invalid enable value

- **WHEN** `AUTO_RESTART_ENABLED` is not a recognized boolean
- **THEN** Auto Restart SHALL remain disabled

### Requirement: Schedule expression

`AUTO_RESTART_CRON` SHALL hold one schedule expression: a numeric five-field cron expression or an
elapsed schedule of the form `@every <amount><unit>`. The unit SHALL be one of `s`, `m`, `h`, or
`d`, and the amount SHALL be a positive integer. The expression SHALL be case-insensitive for the
`@every` prefix and unit.

#### Scenario: Cron schedule accepted

- **WHEN** `AUTO_RESTART_CRON` is a numeric five-field cron expression
- **THEN** the schedule SHALL be accepted

#### Scenario: Elapsed schedule accepted

- **WHEN** `AUTO_RESTART_CRON` is `@every 24h`
- **THEN** the schedule SHALL be accepted

#### Scenario: Elapsed schedule is case-insensitive

- **WHEN** `AUTO_RESTART_CRON` is `@EVERY 1D`
- **THEN** the schedule SHALL be accepted as a one-day interval

### Requirement: Invalid schedule handling

An enabled configuration with an empty or invalid expression SHALL log an error naming
`AUTO_RESTART_CRON` and SHALL run no automatic restart; the server SHALL keep running.

#### Scenario: Empty schedule fails closed

- **WHEN** `AUTO_RESTART_ENABLED=true` and `AUTO_RESTART_CRON` is empty
- **THEN** an error SHALL name `AUTO_RESTART_CRON`
- **AND** no automatic restart SHALL occur
- **AND** the server SHALL keep running

#### Scenario: Invalid schedule fails closed

- **WHEN** `AUTO_RESTART_ENABLED=true` and `AUTO_RESTART_CRON` cannot be parsed
- **THEN** an error SHALL name `AUTO_RESTART_CRON` and describe the invalid value
- **AND** no automatic restart SHALL occur
- **AND** the server SHALL keep running

#### Scenario: Invalid elapsed amount

- **WHEN** `AUTO_RESTART_CRON` contains `@every 0h` or a non-positive amount
- **THEN** the schedule SHALL be rejected as invalid

### Requirement: Cron field syntax

A cron schedule SHALL use five fields in the order minute, hour, day-of-month, month, and
day-of-week. Each field SHALL accept `*`, comma-separated lists, inclusive ranges, and steps in the
form `*/N` or `a-b/N`. A step SHALL NOT be attached to a bare value. Numeric values SHALL use
minute `0-59`, hour `0-23`, day-of-month `1-31`, month `1-12`, and day-of-week `0-7`, where `0` and
`7` both mean Sunday. Only ASCII digits SHALL be accepted, and month and weekday names SHALL NOT be
accepted.

#### Scenario: Lists, ranges, and steps accepted

- **WHEN** `AUTO_RESTART_CRON=15,45 8-10 */2 * *`
- **THEN** the schedule SHALL be accepted

#### Scenario: Sunday aliases

- **WHEN** `AUTO_RESTART_CRON=0 9 * * 7`
- **THEN** the schedule SHALL match Sunday

#### Scenario: Names and non-ASCII digits are rejected

- **WHEN** `AUTO_RESTART_CRON` contains `MON` or a non-ASCII digit
- **THEN** the schedule SHALL be rejected as invalid

#### Scenario: Bare-value steps are rejected

- **WHEN** `AUTO_RESTART_CRON` contains a step on a bare value such as `5/2`
- **THEN** the schedule SHALL be rejected as invalid

### Requirement: Day field restriction

A day-of-month or day-of-week field SHALL be restricted when it does not cover every possible
value. When both fields are restricted, either field matching SHALL trigger the restart; when either
field covers every value, both SHALL match.

#### Scenario: Restricted day fields are ORed

- **WHEN** `AUTO_RESTART_CRON=0 9 2 * 1`
- **THEN** the schedule SHALL match the second of the month or any Monday

#### Scenario: All-value day fields are unrestricted

- **WHEN** `AUTO_RESTART_CRON=0 9 */1 * 1`
- **THEN** the schedule SHALL match Mondays only

### Requirement: Cron timing

Cron schedules SHALL use the configured `TZ`. A cron schedule SHALL NOT run a catch-up restart. Its
first trigger SHALL be strictly after the server launches, and a trigger missed while the server was
stopped or restarting SHALL wait for the next matching time. A schedule with no occurrence within
five years SHALL be treated as invalid.

#### Scenario: Daily wall-clock restart

- **WHEN** `AUTO_RESTART_CRON=0 9 * * *` and the server is running before 9 AM
- **THEN** the restart SHALL become due at 9 AM in the configured `TZ`

#### Scenario: Next trigger after launch

- **WHEN** the server launches exactly on a scheduled minute
- **THEN** that minute SHALL NOT trigger a restart
- **AND** the next matching time SHALL be used

#### Scenario: Missed trigger is not caught up

- **WHEN** a scheduled time passes while the server is stopped
- **THEN** no restart SHALL run when the server starts
- **AND** the next matching time SHALL be used

#### Scenario: Impossible schedule fails closed

- **WHEN** `AUTO_RESTART_CRON=0 0 30 2 *`
- **THEN** the schedule SHALL be rejected because it never occurs

### Requirement: Elapsed schedule semantics

An `@every` schedule SHALL measure from the launch of the current server process. The first trigger
SHALL occur after the configured interval, and each relaunch, including an update, rollback, or
recovery relaunch, SHALL restart the measurement.

#### Scenario: Daily uptime restart

- **WHEN** `AUTO_RESTART_CRON=@every 24h` and the server launches
- **THEN** the restart SHALL become due 24 hours after that launch

#### Scenario: Relaunch resets the interval

- **WHEN** an update restart relaunches the server before the elapsed interval expires
- **THEN** the next scheduled restart SHALL be 24 hours after the relaunch

### Requirement: Grace window setting

`AUTO_RESTART_MAX_DELAY` SHALL default to 3600 seconds and SHALL accept integer seconds. A
non-integer value SHALL fall back to 3600, and a negative value SHALL clamp to 0. A value of 0 SHALL
restart immediately at the scheduled time.

#### Scenario: Zero grace restarts immediately

- **WHEN** `AUTO_RESTART_MAX_DELAY=0` and the scheduled time arrives
- **THEN** the restart SHALL proceed even if players are online

#### Scenario: Invalid grace falls back

- **WHEN** `AUTO_RESTART_MAX_DELAY` is not an integer
- **THEN** the grace window SHALL be 3600 seconds

#### Scenario: Negative grace clamps

- **WHEN** `AUTO_RESTART_MAX_DELAY` is negative
- **THEN** the grace window SHALL be 0 seconds

### Requirement: Player activity evidence

Player activity SHALL use the active player handle, pending join, and remote machine evidence
defined by `auto-pause` (see `auto-pause`). Auto Restart SHALL NOT apply that capability's A2S
veto, world-ready requirement, stdout-stream health, or tracker-degradation veto. It SHALL waive
Session-block freshness, completeness, and malformation, but a recognized remote-machine row
(`m#N` with `N>0`) in the latest complete Session block SHALL count as player activity.

#### Scenario: Remote machine delays the restart

- **WHEN** a scheduled restart becomes due, no player handle or pending join exists, and the latest
  complete Session block contains a recognized `m#1` row
- **THEN** the server SHALL keep running
- **AND** a warning SHALL state that the restart is waiting for players

#### Scenario: A2S and health vetoes do not delay

- **WHEN** A2S reports players or is unresolved, the world is not ready, the stdout stream has ended,
  or the tracker is degraded, while no player handle, pending join, or recognized remote-machine
  row exists
- **THEN** the restart SHALL proceed at the due time

### Requirement: Player activity deferral

When a restart becomes due, it SHALL run immediately if no player activity is present. While player
activity remains, a warning SHALL be logged and the restart SHALL wait until the activity clears or
the grace window expires.

#### Scenario: Empty server restarts at the due time

- **WHEN** a scheduled restart becomes due and no player activity is present
- **THEN** the server SHALL restart immediately

#### Scenario: Players delay the restart

- **WHEN** a scheduled restart becomes due while a player is online
- **THEN** the server SHALL keep running
- **AND** a warning SHALL state that the restart is waiting for players

### Requirement: Grace expiry

The grace window SHALL start at the scheduled trigger time. When it expires, a warning SHALL be
logged and the restart SHALL proceed regardless of player activity.

#### Scenario: Players leave during the grace window

- **WHEN** a delayed restart's player activity clears before the grace expires
- **THEN** the restart SHALL proceed without waiting for the deadline

#### Scenario: Grace expires with players online

- **WHEN** player activity remains when the grace window expires
- **THEN** a warning SHALL state that the grace expired
- **AND** the restart SHALL proceed

### Requirement: Paused tree restart

A scheduled restart SHALL restart a paused tree through the ordered exit path. Pause and resume
policy SHALL follow `auto-pause`.

#### Scenario: Paused tree restarts

- **WHEN** a scheduled restart becomes due while Auto Pause reports the tree paused
- **THEN** the tree SHALL resume before the server receives the shutdown signal
- **AND** the server SHALL relaunch with a new PID

### Requirement: Restart depth and Active Manifest

A scheduled restart SHALL use the in-process relaunch owned by `server-lifecycle` and SHALL NOT
change the Active Manifest. It SHALL NOT run Install, rebuild the Game tree, or regenerate the
Generated config.

#### Scenario: Active Manifest stays active

- **WHEN** a scheduled restart completes
- **THEN** the Active Manifest SHALL be the same Manifest as before the restart

#### Scenario: No install or staging

- **WHEN** a scheduled restart runs
- **THEN** no Download SHALL start
- **AND** no Manifest selection SHALL change

### Requirement: Cross-feature precedence

An update restart accepted by the server lifecycle SHALL take precedence over a due scheduled
restart. Auto Restart SHALL NOT run while auto rollback is active. A scheduled trigger that falls
shortly after any relaunch SHALL still be honored; no minimum-uptime guard SHALL suppress it.

#### Scenario: Update restart wins

- **WHEN** Auto Update requests a restart and a scheduled restart is also due
- **THEN** the update restart SHALL proceed
- **AND** the scheduled restart SHALL NOT preempt it

#### Scenario: Rollback disables Auto Restart

- **WHEN** auto rollback is active
- **THEN** no scheduled restart SHALL occur

#### Scenario: No minimum uptime

- **WHEN** a scheduled trigger falls shortly after an update or recovery relaunch
- **THEN** the trigger SHALL still be honored

### Requirement: Failure isolation and shutdown

A schedule evaluation or Auto Restart failure SHALL be logged and SHALL leave the server running
without requesting a restart. Shutdown SHALL abort a pending grace wait and SHALL NOT restart the
server. A failed restart stop SHALL follow `server-lifecycle`.

#### Scenario: Auto Restart failure leaves the server running

- **WHEN** Auto Restart fails unexpectedly
- **THEN** the error SHALL be logged
- **AND** the server SHALL keep running

#### Scenario: Shutdown during the grace window

- **WHEN** shutdown begins while a scheduled restart waits for players
- **THEN** no restart SHALL occur
- **AND** the container SHALL exit through the shutdown path

### Requirement: Auto Restart logging

Auto Restart SHALL log an INFO startup line naming the schedule and the next run. A frequent
schedule, a due restart waiting for players, and a grace expiry SHALL be logged at WARNING. A
restart request SHALL be logged at INFO. Auto Restart warnings SHALL follow the orchestrator
file-logging level rules (see `orchestrator-file-logging`).

#### Scenario: Startup line names the next run

- **WHEN** Auto Restart is enabled with a valid schedule
- **THEN** startup SHALL log the schedule and the next run

#### Scenario: Frequent schedule warns

- **WHEN** the next computed delay is under 15 minutes
- **THEN** a WARNING SHALL name the frequent schedule
- **AND** the restart SHALL still run at the scheduled time

#### Scenario: Deferred restart warns

- **WHEN** a due restart waits for players
- **THEN** a WARNING SHALL describe the wait
- **AND** a WARNING SHALL describe the grace expiry when it occurs

#### Scenario: Restart request is logged

- **WHEN** Auto Restart requests the in-process restart
- **THEN** an INFO line SHALL state that the restart is starting
