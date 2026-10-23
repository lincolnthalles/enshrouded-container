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

### Requirement: Thin entrypoint

The entrypoint SHALL contain only argument parsing, logging setup, CLI-flag-to-settings merging, settings loading, and subcommand dispatch. It SHALL NOT contain business logic, signal handling, or process management code.

#### Scenario: Unknown subcommand rejected at entrypoint

- **WHEN** the container runs `enshctl` with an unknown subcommand name
- **THEN** argument parsing SHALL reject it with a non-zero exit and name the known subcommands, before any business logic runs
