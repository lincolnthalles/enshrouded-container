## Purpose

Fedora-based container image providing plain Wine as the game execution runtime.

## Requirements

### Requirement: Plain Wine runtime

The container SHALL provide plain Wine from the Fedora repositories (`wine-core`, `wine-common`, `wine-ldap`). The Wine prefix at `/data/wineprefix` SHALL be initialized with `wineboot --init` on first start. The game server SHALL be launched via `wine` (wrapped in `xvfb-run` and `runuser -u steam`), not via Proton.

#### Scenario: Wine prefix is initialized

- **WHEN** the container starts and `/data/wineprefix/.wineboot-completed` does not exist
- **THEN** `wine wineboot --init` SHALL run as the `steam` user under `xvfb-run`

#### Scenario: Wine prefix is reused once initialized

- **WHEN** the container starts and `/data/wineprefix/.wineboot-completed` exists
- **THEN** prefix initialization SHALL be skipped

#### Scenario: Plain Wine is the game execution runtime

- **WHEN** the game server is started
- **THEN** the server SHALL be launched via `wine` (`/usr/bin/runuser -u steam -- xvfb-run … wine <exe>`) rather than Proton

### Requirement: Image contains required packages

The container image SHALL include: `python3`, `python3-pip` (build only), `procps-ng`, `util-linux`, `xorg-x11-server-Xvfb`, `wine-core`, `wine-common`, `wine-ldap`. The `Dockerfile` SHALL NOT require WineHQ repositories, `winetricks`, GE-Proton, or .NET runtimes in the final stage.

#### Scenario: Image builds successfully

- **WHEN** `docker build` is run with the Dockerfile
- **THEN** the image builds without errors and produces a runnable container

#### Scenario: Image contains required packages

- **WHEN** the image is inspected
- **THEN** the following packages SHALL be present: `python3`, `procps-ng`, `util-linux`, `xorg-x11-server-Xvfb`, `wine-core`, `wine-common`, `wine-ldap`

### Requirement: Steam user and directory structure

The container SHALL create a non-root `steam` user (UID/GID configurable via `PUID`/`PGID` env vars, default 1000/1000) and the following directories: `/data/backups`, `/data/config`, `/data/logs`, `/data/manifests`, `/data/mods`, `/data/saves`, `/data/wineprefix`. All data directories SHALL be owned by `steam:steam`.

#### Scenario: Steam user exists

- **WHEN** the container starts
- **THEN** the `steam` user SHALL exist with the configured UID/GID and a home directory at `/home/steam`

#### Scenario: Data directories exist with correct ownership

- **WHEN** the container starts
- **THEN** all data directories SHALL exist and be owned by `steam:steam`
