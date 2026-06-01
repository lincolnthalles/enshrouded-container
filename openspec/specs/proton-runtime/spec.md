## ADDED Requirements

### Requirement: GE-Proton download and installation

The Dockerfile SHALL download GE-Proton from GitHub releases using a pinned `ARG GE_PROTON_VERSION`. A builder stage SHALL download and extract the tarball to `/opt/proton/` with `--strip-components=1`. The final stage SHALL copy `/opt/proton/` from the builder.

#### Scenario: GE-Proton is available at runtime

- **WHEN** the container starts
- **THEN** `/opt/proton/proton` SHALL exist and be executable

#### Scenario: GE-Proton version is pinned and overridable

- **WHEN** `docker build` is run
- **THEN** `GE_PROTON_VERSION` SHALL default to `10-32` and be overridable via `--build-arg`

### Requirement: Machine ID generation

The Dockerfile SHALL generate `/etc/machine-id` via `dbus-uuidgen --ensure=/etc/machine-id` in the builder stage. The final stage SHALL copy this file from the builder.

#### Scenario: Machine ID exists at runtime

- **WHEN** the container starts
- **THEN** `/etc/machine-id` SHALL exist and contain a valid UUID

### Requirement: Proton environment variables

The Dockerfile SHALL set the following environment variables:

- `STEAM_COMPAT_APP_ID=2278520`
- `STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/steam/steamcmd`
- `STEAM_COMPAT_DATA_PATH=/home/steam/.proton`
- `UMU_ID=0`

#### Scenario: STEAM_COMPAT_APP_ID is set

- **WHEN** the container starts
- **THEN** `STEAM_COMPAT_APP_ID` SHALL be `2278520`

#### Scenario: STEAM_COMPAT_DATA_PATH points to proton prefix

- **WHEN** the container starts
- **THEN** `STEAM_COMPAT_DATA_PATH` SHALL be `/home/steam/.proton`

### Requirement: Proton prefix directory ownership

The Proton prefix directory `/home/steam/.proton` SHALL be created and owned by the `steam` user. Proton SHALL create the prefix subdirectory structure (`pfx/`, `dosdevices/`, etc.) on first run.

#### Scenario: Proton prefix directory exists

- **WHEN** the container starts
- **THEN** `/home/steam/.proton` SHALL exist and be owned by `steam:steam`

### Requirement: Proton version reporting

The `version-info` subcommand SHALL report the GE-Proton version alongside the Wine version.

#### Scenario: Version info output includes Proton version

- **WHEN** `enshrouded-server version-info` is run
- **THEN** the output SHALL include the GE-Proton version string

### Requirement: Proton Wine server cleanup on shutdown

The shutdown handler SHALL kill Proton's Wine server process using `/opt/proton/files/bin/wineserver -k` after the game server process exits.

#### Scenario: Wine server is cleaned up on shutdown

- **WHEN** the container receives SIGTERM and the game server exits
- **THEN** `/opt/proton/files/bin/wineserver -k` SHALL be executed to clean up Wine server processes

### Requirement: Steam client bridge activation

The server launch command SHALL set `UMU_USE_STEAM=1` in the subprocess environment. This activates Proton's Steam client bridge, which launches the game via `steam.exe` with `lsteamclient=d` Wine override, providing `steamclient64.dll` to the game.

#### Scenario: UMU_USE_STEAM is set during server launch

- **WHEN** the server process is started via `_start_server()`
- **THEN** the subprocess environment SHALL contain `UMU_USE_STEAM=1`

#### Scenario: Steam client bridge is active

- **WHEN** the server starts with `UMU_USE_STEAM=1`
- **THEN** Proton SHALL launch the game via `c:\windows\system32\steam.exe` instead of `umu.exe`

### Requirement: Steam App ID file

The startup sequence SHALL create `steam_appid.txt` in the game directory containing the Steam app ID (2278520) before launching the server. This file is required by `steam.exe` to identify the correct game.

#### Scenario: steam_appid.txt exists before server launch

- **WHEN** the startup sequence reaches the server launch step
- **THEN** `steam_appid.txt` SHALL exist in the game directory and contain `2278520`

#### Scenario: steam_appid.txt is created for new installations

- **WHEN** a game version is downloaded via DepotDownloader
- **THEN** `steam_appid.txt` SHALL be created in the downloaded game directory
