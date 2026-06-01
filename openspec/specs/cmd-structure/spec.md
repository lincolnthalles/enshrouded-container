### Requirement: Subcommand dispatch via cmd package

The entrypoint SHALL dispatch CLI subcommands to dedicated modules under `enshrouded_server.commands`. Each subcommand (`start`, `install`, `backup`, `restore`, `verify`, `prune`, `download`, `version-info`, `debug-config`) SHALL be implemented in its own module under `commands/` exposing a `run()` function.

#### Scenario: CLI dispatch to cmd module

- **WHEN** the container runs `enshrouded-server start`
- **THEN** the entrypoint SHALL call `commands.start.run()`

#### Scenario: CLI dispatch for backup subcommand

- **WHEN** the container runs `enshrouded-server backup`
- **THEN** the entrypoint SHALL call `commands.backup.run()`

#### Scenario: CLI dispatch for restore subcommand

- **WHEN** the container runs `enshrouded-server restore`
- **THEN** the entrypoint SHALL call `commands.restore.run()`

#### Scenario: CLI dispatch for verify subcommand

- **WHEN** the container runs `enshrouded-server verify`
- **THEN** the entrypoint SHALL call `commands.verify.run()`

#### Scenario: CLI dispatch for prune subcommand

- **WHEN** the container runs `enshrouded-server prune`
- **THEN** the entrypoint SHALL call `commands.prune.run()`

### Requirement: Subcommand module interface

Each `cmd` module SHALL expose a `run()` function as its public entrypoint. The module MAY define additional private helper functions. Each `run()` function SHALL be type-annotated and return `None`.

#### Scenario: cmd module has run function

- **WHEN** `cmd.start` is imported
- **THEN** `cmd.start.run` SHALL be a callable that returns `None`

#### Scenario: cmd module keeps helpers private

- **WHEN** `cmd.start` is imported
- **THEN** subcommand-internal functions (e.g., `_setup_directories`, `_start_server`) SHALL be module-level private functions (underscore-prefixed)

### Requirement: Thin entrypoint

The `__main__.py` module SHALL contain only argument parsing, logging setup, and subcommand dispatch. It SHALL NOT contain business logic, signal handling, or process management code.

#### Scenario: Entry point has no business logic

- **WHEN** `__main__.py` is inspected
- **THEN** it SHALL contain only: argument parser definition, `main()` function, and dispatch to `cmd.*.run()` — no functions exceeding 20 lines of business logic

### Requirement: Restore subcommand dispatch

The entrypoint SHALL dispatch the `restore` subcommand to `commands/restore.py`.

#### Scenario: CLI dispatch for restore

- **WHEN** the container runs `enshrouded-server restore`
- **THEN** the entrypoint SHALL call `commands.restore.run()`

### Requirement: Verify subcommand dispatch

The entrypoint SHALL dispatch the `verify` subcommand to `commands/verify.py`.

#### Scenario: CLI dispatch for verify

- **WHEN** the container runs `enshrouded-server verify`
- **THEN** the entrypoint SHALL call `commands.verify.run()`

### Requirement: Prune subcommand dispatch

The entrypoint SHALL dispatch the `prune` subcommand to `commands/prune.py`.

#### Scenario: CLI dispatch for prune

- **WHEN** the container runs `enshrouded-server prune`
- **THEN** the entrypoint SHALL call `commands.prune.run()`
