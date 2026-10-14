## Purpose

Dispatch of CLI subcommands to dedicated modules under the commands package.

## Requirements

### Requirement: Subcommand dispatch via commands package

The entrypoint SHALL dispatch CLI subcommands to dedicated modules under `enshctl.commands`. Each subcommand (`start`, `install`, `backup`, `restore`, `verify`, `prune`, `download`, `version-info`, `debug-config`) SHALL be registered in the `COMMANDS` registry in `enshctl/commands/__init__.py` and implemented in its own module under `commands/` exposing a `run()` function.

#### Scenario: CLI dispatch to commands module

- **WHEN** the container runs `enshctl start`
- **THEN** the entrypoint SHALL call `commands.start.run()` via the `COMMANDS` registry

#### Scenario: CLI dispatch for backup subcommand

- **WHEN** the container runs `enshctl backup`
- **THEN** the entrypoint SHALL call `commands.backup.run()`

#### Scenario: CLI dispatch for restore subcommand

- **WHEN** the container runs `enshctl restore`
- **THEN** the entrypoint SHALL call `commands.restore.run()`

#### Scenario: CLI dispatch for verify subcommand

- **WHEN** the container runs `enshctl verify`
- **THEN** the entrypoint SHALL call `commands.verify.run()`

#### Scenario: CLI dispatch for prune subcommand

- **WHEN** the container runs `enshctl prune`
- **THEN** the entrypoint SHALL call `commands.prune.run()`

### Requirement: Subcommand module interface

Each `commands` module SHALL expose a `run()` function as its public entrypoint. The module MAY define additional private helper functions. Each `run()` function SHALL be type-annotated and return `None`.

#### Scenario: commands module has run function

- **WHEN** `enshctl.commands.start` is imported
- **THEN** `enshctl.commands.start.run` SHALL be a callable that returns `None`

#### Scenario: commands module keeps helpers private

- **WHEN** `enshctl.commands.start` is imported
- **THEN** subcommand-internal functions (e.g., `_setup_directories`, `_start_server`) SHALL be module-level private functions (underscore-prefixed)

### Requirement: Thin entrypoint

The `__main__.py` module SHALL contain only argument parsing, logging setup (console plus the opt-in orchestrator file handler), CLI-flag-to-environment mapping, settings loading, and subcommand dispatch. It SHALL NOT contain business logic, signal handling, or process management code.

#### Scenario: Entry point has no business logic

- **WHEN** `__main__.py` is inspected
- **THEN** it SHALL contain only: argument parser definition, CLI-flag-to-environment mapping, logging setup including the `_GameServerFilter` filter class, `main()` function, and dispatch via the `COMMANDS` registry — no signal handling or process management code
