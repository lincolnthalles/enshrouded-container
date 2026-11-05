## Purpose

Dispatch of CLI subcommands to dedicated modules under the commands package.

## Requirements

### Requirement: Subcommand dispatch

The entrypoint SHALL expose each CLI subcommand (`start`, `install`, `backup`, `restore`, `verify`,
`prune`, `download`, `version-info`, `debug-config`, `autopause`) and dispatch it to the command
implementation for that name.

#### Scenario: CLI dispatch to commands module

- **WHEN** the container runs `enshctl start`
- **THEN** the start command SHALL execute

#### Scenario: CLI dispatch for backup subcommand

- **WHEN** the container runs `enshctl backup`
- **THEN** the backup command SHALL execute

#### Scenario: CLI dispatch for restore subcommand

- **WHEN** the container runs `enshctl restore`
- **THEN** the restore command SHALL execute

#### Scenario: CLI dispatch for verify subcommand

- **WHEN** the container runs `enshctl verify`
- **THEN** the verify command SHALL execute

#### Scenario: CLI dispatch for prune subcommand

- **WHEN** the container runs `enshctl prune`
- **THEN** the prune command SHALL execute

#### Scenario: CLI dispatch for install subcommand

- **WHEN** the container runs `enshctl install`
- **THEN** the install command SHALL execute

#### Scenario: CLI dispatch for download subcommand

- **WHEN** the container runs `enshctl download`
- **THEN** the download command SHALL execute

#### Scenario: CLI dispatch for version-info subcommand

- **WHEN** the container runs `enshctl version-info`
- **THEN** the version report SHALL be printed

#### Scenario: CLI dispatch for debug-config subcommand

- **WHEN** the container runs `enshctl debug-config`
- **THEN** the generated configuration SHALL be printed

#### Scenario: CLI dispatch for autopause subcommand

- **WHEN** the container runs `enshctl autopause status`
- **THEN** the Auto Pause command SHALL execute

### Requirement: Command exit contract

Each command module SHALL return an integer process exit code for handled outcomes. Parser usage errors and `--help` SHALL propagate their `SystemExit` code through the entrypoint. The entrypoint SHALL exit with the returned command code or the propagated parser code. Unexpected dispatcher-handled errors SHALL be logged and exit 1.

#### Scenario: Successful command returns zero

- **WHEN** a command completes successfully
- **THEN** it SHALL return 0 and the entrypoint SHALL exit 0

#### Scenario: Failed command returns non-zero

- **WHEN** a command fails in a way it handles
- **THEN** it SHALL return a non-zero code and the entrypoint SHALL exit with that code

#### Scenario: Parser usage exit propagates

- **WHEN** a command's parser exits with a usage or help code
- **THEN** the entrypoint SHALL exit with that code

#### Scenario: Unexpected error exits one

- **WHEN** a dispatcher-handled error escapes a command
- **THEN** the entrypoint SHALL log the error and exit 1

### Requirement: Thin entrypoint

The entrypoint SHALL contain only argument parsing, logging setup, CLI-flag-to-settings merging, settings loading, and subcommand dispatch. It SHALL NOT contain business logic, signal handling, or process management code.

#### Scenario: Unknown subcommand rejected at entrypoint

- **WHEN** the container runs `enshctl` with an unknown subcommand name
- **THEN** argument parsing SHALL reject it with a non-zero exit and name the known subcommands, before any business logic runs

### Requirement: Auto Pause command actions

The `autopause` command SHALL support `status`, `pause [--force]`, `resume`, `reset [--yes]`,
`disable`, and `enable`. `pause`, `resume`, and `reset` SHALL require a live controller. `disable`
and `enable` SHALL work without a live controller and SHALL exit 0 after a durable marker write.

#### Scenario: Disable works without a controller

- **WHEN** `autopause disable` runs with no live controller
- **THEN** the `disabled` marker SHALL be written
- **AND** the command SHALL exit 0

#### Scenario: Disable resumes a paused tree

- **WHEN** `autopause disable` runs while the controller is paused
- **THEN** the controller SHALL resume the tree
- **AND** the command SHALL exit 0 after the marker is durable

#### Scenario: Enable removes the marker

- **WHEN** `autopause enable` runs with no live controller
- **THEN** the `disabled` marker SHALL be removed
- **AND** the command SHALL exit 0

### Requirement: Auto Pause exit contract

`status` SHALL exit 0 only when a live controller is fresh; stale or missing status SHALL exit 3.
`pause`, `resume`, and `reset` SHALL exit 3 when no live controller is available. A consumed
request SHALL exit 0 when pending, applied, or a no-op success, and 2 when refused. A request not
consumed within 5 seconds SHALL exit 3 and SHALL be ignored if consumed later.

#### Scenario: Status reports a live controller

- **WHEN** `autopause status` runs while a fresh controller PID is alive
- **THEN** the command SHALL print the current state and exit 0

#### Scenario: Status reports stale state

- **WHEN** `autopause status` runs with missing, stale, or PID-gone status
- **THEN** the command SHALL print the unavailable state and exit 3

#### Scenario: Request accepted

- **WHEN** `autopause pause` writes a tokenized request and the controller reports that token as
  pending
- **THEN** the command SHALL exit 0

#### Scenario: Request refused

- **WHEN** `autopause pause` is refused because a player is online
- **THEN** the command SHALL exit 2

#### Scenario: Request times out

- **WHEN** no controller consumes a request within 5 seconds
- **THEN** the command SHALL exit 3

#### Scenario: Reset requires a live controller

- **WHEN** `autopause reset` runs with no live controller
- **THEN** the command SHALL exit 3
- **AND** no handles SHALL be cleared

#### Scenario: Reset roster refusal

- **WHEN** a live controller reports an active player and `autopause reset` runs without `--yes`
- **THEN** the command SHALL exit 2
- **AND** no handles SHALL be cleared
