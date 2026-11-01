## Purpose

Server startup ordering from Install through launch; shutdown and crash behavior live in `backup-system`, execution isolation in `backup-subprocess`, Game tree construction in `game-tree-rebuild`, config generation in `config-management`, DLL override generation in `dll-override-generation`.

## Requirements

### Requirement: Startup sequence

The entrypoint SHALL execute the following startup sequence in order: (1) Install the game Version spec, (2) build the Game tree, (3) generate the Generated config, (4) launch the server executable under Wine with resolved DLL overrides in its environment. The server's environment SHALL carry no Steam AppID variable; the app ID SHALL reach DepotDownloader as a command argument only.

#### Scenario: Full startup sequence

- **WHEN** the container starts with a valid Version spec and save data paths configured
- **THEN** the following SHALL happen in order:
  1. The Manifest ID is resolved and its Manifest install ensured
  2. The Game tree is built from the Manifest install and Mod overlay
  3. The Generated config is written to the config directory
  4. The server executable is launched under Wine with DLL overrides resolved at launch time (see `dll-override-generation`)

#### Scenario: Startup fails fast

- **WHEN** any startup step fails (e.g. network error during Download)
- **THEN** the container SHALL exit with a non-zero code

### Requirement: PID file lifecycle

After launching the server, the entrypoint SHALL write the launched server process PID to the PID file. Every exit after a successful write SHALL clear the PID file. A failed write SHALL NOT remove a marker the process did not write. Presence of the PID file is the restore guard (see `backup-restore`).

#### Scenario: PID file written on launch

- **WHEN** the game server process is launched
- **THEN** the entrypoint SHALL write the launched process PID to the PID file before supervising it

#### Scenario: PID file cleared on shutdown

- **WHEN** the container shuts down after the server has launched
- **THEN** the PID file SHALL be cleared

#### Scenario: PID file cleared on crash

- **WHEN** the game server exits unexpectedly
- **THEN** the PID file SHALL be cleared
