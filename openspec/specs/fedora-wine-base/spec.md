## MODIFIED Requirements

### Requirement: Wine 11 runtime

The container SHALL provide Wine 11 (staging branch) via the WineHQ Fedora repository as a dependency for GE-Proton and winetricks. The Wine prefix at `/wine` SHALL be initialized with `wineboot --init` for winetricks dependency installation. GE-Proton at `/opt/proton/` SHALL be the primary runtime for game execution.

#### Scenario: Wine prefix is initialized

- **WHEN** the container is built
- **THEN** a Wine prefix SHALL be created at `/wine` with `winearch=win64` for winetricks operations

#### Scenario: Winetricks dependencies are installed

- **WHEN** the container is built
- **THEN** corefonts, vcrun2019, vcrun2022, and vcrun2026 SHALL be installed in the system Wine prefix at `/wine`

#### Scenario: Proton is the game execution runtime

- **WHEN** the game server is started
- **THEN** the server SHALL be launched via `/opt/proton/proton run` rather than `wine`

### Requirement: Image contains required packages

The container image SHALL include: `winehq-staging`, `winetricks`, `zstd`, `python3`, `python3-pip`, `dotnet-runtime-8.0`, `curl`, `unzip`, `procps-ng`, `rsync`, `fuse-libs`, `funionfs`, `xorg-x11-server-Xvfb`, `glibc-langpack-en`, `util-linux`, `cabextract`, `dbus`, `tar`.

#### Scenario: Image builds successfully

- **WHEN** `docker build` is run with the Dockerfile
- **THEN** the image builds without errors and produces a runnable container

#### Scenario: Image contains required packages

- **WHEN** the image is inspected
- **THEN** the following packages SHALL be present: `winehq-staging`, `winetricks`, `zstd`, `python3`, `python3-pip`, `dotnet-runtime-8.0`, `curl`, `unzip`, `procps-ng`, `dbus`, `tar`

### Requirement: Steam user and directory structure

The container SHALL create a non-root `steam` user (UID/GID configurable via `PUID`/`PGID` env vars, default 1000/1000) and the following directories: `/wine`, `/home/steam/.proton`, `/home/steam/steamcmd`, `/home/steam/.steam`, `/data/game`, `/data/mods`, `/data/saves`, `/data/backups`, `/data/logs`, `/data/.unionfs-work`, `/config`.

#### Scenario: Steam user exists

- **WHEN** the container starts
- **THEN** the `steam` user SHALL exist with the configured UID/GID and a home directory at `/home/steam`

#### Scenario: Data directories exist with correct ownership

- **WHEN** the container starts
- **THEN** all data directories SHALL exist and be owned by `steam:steam`

## REMOVED Requirements

None — all existing requirements are modified, not removed.
