## Purpose

Dispatch of CLI subcommands to dedicated modules under the commands package.

## Requirements

### Requirement: Subcommand dispatch

The entrypoint SHALL dispatch each CLI subcommand (`start`, `install`, `backup`, `restore`, `verify`, `prune`, `download`, `version-info`, `debug-config`) to its dedicated commands module.

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
