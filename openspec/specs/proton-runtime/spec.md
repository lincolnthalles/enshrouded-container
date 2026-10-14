## Purpose

Plain-Wine game execution environment: launch, prefix lifecycle, and version reporting.

## Requirements

### Requirement: Wine server launch

The `_start_server()` function SHALL launch the game via `/usr/bin/runuser -u steam -- xvfb-run --auto-servernum wine <game-exe>` with `cwd=/data/gameserver`. The subprocess environment SHALL include `WINEPREFIX=/data/wineprefix`, `WINEARCH`, `WINEDEBUG`, and the resolved `WINEDLLOVERRIDES`.

#### Scenario: Server launches under Wine via xvfb-run

- **WHEN** the server process is started via `_start_server()`
- **THEN** the command SHALL invoke `wine` wrapped in `runuser -u steam` and `xvfb-run --auto-servernum`

#### Scenario: Wine environment is set during server launch

- **WHEN** the server process is started via `_start_server()`
- **THEN** the subprocess environment SHALL contain `WINEPREFIX=/data/wineprefix` and the resolved `WINEDLLOVERRIDES`

### Requirement: Machine ID generation

The Dockerfile SHALL generate `/etc/machine-id` from the kernel UUID (`cat /proc/sys/kernel/random/uuid > /etc/machine-id`) during the image build.

#### Scenario: Machine ID exists at runtime

- **WHEN** the container starts
- **THEN** `/etc/machine-id` SHALL exist and contain a valid UUID

### Requirement: Wine prefix directory ownership

The Wine prefix directory `/data/wineprefix` SHALL be created and owned by the `steam` user. Wine SHALL create the prefix subdirectory structure (`drive_c/`, `*.reg`, etc.) on first init via `wineboot --init`.

#### Scenario: Wine prefix directory exists

- **WHEN** the container starts
- **THEN** `/data/wineprefix` SHALL exist and be owned by `steam:steam`

### Requirement: Version reporting

The `version-info` subcommand SHALL report installed game versions (manifest ID and install timestamp for each directory under `/data/manifests/` carrying a `.installed` marker). No Proton or Wine version detection is required.

#### Scenario: Version info lists installed manifests

- **WHEN** `enshctl version-info` is run
- **THEN** the output SHALL list each installed manifest ID with its install timestamp

### Requirement: Wine server cleanup on shutdown

The shutdown handler SHALL kill the Wine server process using `/usr/bin/wineserver -k` (falling back to `-k9` on timeout) after the game server process exits.

#### Scenario: Wine server is cleaned up on shutdown

- **WHEN** the container receives SIGTERM and the game server exits
- **THEN** `/usr/bin/wineserver -k` SHALL be executed to clean up Wine server processes
