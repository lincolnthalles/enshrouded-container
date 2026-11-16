## Purpose

Server startup ordering from Install through launch; shutdown and crash behavior live in `backup-system`, execution isolation in `backup-subprocess`, Game tree construction in `game-tree-rebuild`, config generation in `config-management`, DLL override generation in `dll-override-generation`.

## Requirements

### Requirement: Startup sequence

The entrypoint SHALL execute the following startup sequence in order: (1) Install the game Version spec, (2) build the Game tree, (3) generate the Generated config, (4) launch the server executable under Wine with resolved DLL overrides in its environment. Manifest pruning hooks (see `versioned-game-install`) SHALL run around the sequence without changing its order. The server's environment SHALL carry no Steam AppID variable; the app ID SHALL reach DepotDownloader as a command argument only.

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

### Requirement: In-process update restart

When Auto Update requests a restart (see `auto-update`), the start command SHALL repeat the startup
sequence in the same container after the ordered exit path (see `backup-system`). The repeated
sequence SHALL install the pending Manifest ID selected by Auto Update, build the Game tree from it,
and launch a new server process with a new PID. A failed stop, install, or launch SHALL exit
non-zero and SHALL NOT relaunch.

#### Scenario: Update restart repeats startup

- **WHEN** Auto Update requests a restart after a successful download
- **THEN** the running server SHALL stop
- **AND** the Game tree and Generated config SHALL be rebuilt from the new Manifest install
- **AND** a new server process SHALL launch with a new PID

#### Scenario: Restart uses the pending Manifest

- **WHEN** Auto Update requests a restart for a pending Manifest
- **THEN** the Install, Game tree, and Generated config SHALL use that Manifest ID

#### Scenario: PID file across update restart

- **WHEN** the server stops for an update restart
- **THEN** the PID file SHALL be cleared
- **AND** the relaunched server SHALL write a new PID

#### Scenario: Update stop failure retains the PID

- **WHEN** an update restart cannot stop the server
- **THEN** the PID file SHALL remain
- **AND** the container SHALL exit non-zero

#### Scenario: Rollback stop failure retains the PID

- **WHEN** a rollback restart cannot stop the server (see `auto-rollback`)
- **THEN** the PID file SHALL remain
- **AND** the container SHALL exit non-zero

#### Scenario: Update restart failure exits

- **WHEN** the stop, install, or relaunch step fails during an update restart
- **THEN** the container process SHALL exit non-zero
- **AND** no relaunch SHALL occur

#### Scenario: Shutdown during the restart window

- **WHEN** a shutdown signal arrives before the relaunched server starts
- **THEN** the update restart SHALL abort
- **AND** the container SHALL exit cleanly

### Requirement: In-process recovery restart

When Auto Pause requests a recovery restart (see `auto-pause`), the start command SHALL stop the
server through the ordered exit path, relaunch from the already-prepared Game tree in the same
container, and launch a new server process with a new PID. It SHALL NOT create a Backup and SHALL
NOT repeat Install, Game tree, or Generated config preparation. A stop failure SHALL exit non-zero,
retain the PID file, and SHALL NOT relaunch. A shutdown signal before the relaunch SHALL abort it
and exit cleanly.

#### Scenario: Recovery restart relaunches without staging

- **WHEN** Auto Pause requests a recovery restart
- **THEN** the running server SHALL stop
- **AND** a new server process SHALL launch from the already-prepared Game tree
- **AND** Install, Game tree, and Generated config preparation SHALL NOT run again

#### Scenario: Recovery restart creates no Backup

- **WHEN** a recovery restart runs with cold and emergency backups enabled
- **THEN** no Backup SHALL be created

#### Scenario: Recovery stop failure exits without relaunch

- **WHEN** a recovery restart cannot stop the server
- **THEN** the container SHALL exit non-zero
- **AND** the PID file SHALL remain
- **AND** no relaunch SHALL occur

#### Scenario: Shutdown during the recovery window

- **WHEN** a shutdown signal arrives before the recovery relaunch starts
- **THEN** the recovery restart SHALL abort
- **AND** the container SHALL exit cleanly

### Requirement: In-process scheduled restart

When Auto Restart requests a restart (see `auto-restart`), the start command SHALL stop the
server through the ordered exit path, relaunch from the already-prepared Game tree and Generated
config in the same container, and launch a new server process with a new PID. It SHALL NOT repeat
Install, Game tree, or Generated config preparation, and the Active Manifest SHALL NOT change. The
exit path SHALL apply the cold Backup policy of `backup-system` (see `backup-system`).

#### Scenario: Scheduled restart relaunches without staging

- **WHEN** Auto Restart requests a restart
- **THEN** the running server SHALL stop
- **AND** a new server process SHALL launch from the already-prepared Game tree
- **AND** Install, Game tree, and Generated config preparation SHALL NOT run again

#### Scenario: Scheduled restart keeps the Active Manifest

- **WHEN** a scheduled restart completes
- **THEN** the Active Manifest SHALL be the same Manifest as before the restart

### Requirement: Scheduled restart failure and shutdown

A scheduled stop failure SHALL exit non-zero, retain the PID file, and SHALL NOT relaunch. A
shutdown signal before the relaunch SHALL abort it and exit cleanly.

#### Scenario: Scheduled stop failure exits without relaunch

- **WHEN** a scheduled restart cannot stop the server
- **THEN** the container SHALL exit non-zero
- **AND** the PID file SHALL remain
- **AND** no relaunch SHALL occur

#### Scenario: Shutdown during the scheduled window

- **WHEN** a shutdown signal arrives before the scheduled relaunch starts
- **THEN** the scheduled restart SHALL abort
- **AND** the container SHALL exit cleanly

### Requirement: PID file lifecycle

After launching the server, the entrypoint SHALL write the launched server process PID to the PID file. Every exit after a successful write SHALL clear the PID file, except an update, rollback, recovery, or scheduled restart that cannot stop the server; that path SHALL retain the PID file because the process is still running. A failed write SHALL NOT remove a marker the process did not write. Presence of the PID file is the restore guard (see `backup-restore`).

#### Scenario: PID file written on launch

- **WHEN** the game server process is launched
- **THEN** the entrypoint SHALL write the launched process PID to the PID file before supervising it

#### Scenario: PID file cleared on shutdown

- **WHEN** the container shuts down after the server has launched
- **THEN** the PID file SHALL be cleared

#### Scenario: PID file cleared on crash

- **WHEN** the game server exits unexpectedly
- **THEN** the PID file SHALL be cleared
