## Purpose

Fedora-based container image providing plain Wine as the game execution runtime.

## Requirements

### Requirement: Plain Wine runtime

The container SHALL provide plain Wine from the Fedora repositories; no Proton packages SHALL be present in the final stage. Game launch under Wine is owned by `proton-runtime`.

#### Scenario: Plain Wine is the game execution runtime

- **WHEN** the game server is started
- **THEN** the server SHALL run under plain Wine from the system repositories rather than Proton (see `proton-runtime` for launch)

### Requirement: Image contains required packages

The container image SHALL include the Python runtime, process tools, virtual display server, and Wine packages. The image SHALL NOT require WineHQ repositories, `winetricks`, GE-Proton, or .NET runtimes in the final stage.

#### Scenario: Image builds successfully

- **WHEN** the image is built
- **THEN** the image builds without errors and produces a runnable container

#### Scenario: Image contains required packages

- **WHEN** the image is inspected
- **THEN** the Python runtime, process tools, virtual display, and Wine packages SHALL be present

### Requirement: Steam user and directory structure

The container SHALL create a non-root `steam` user (UID/GID 1000/1000 at build time) and the following directories: `/data/backups`, `/data/config`, `/data/logs`, `/data/manifests`, `/data/mods`, `/data/saves`, `/data/wineprefix`. Runtime directory ownership follows the configured identity (see `shared-config`); the process account itself remains the build-time user.

#### Scenario: Steam user exists

- **WHEN** the container starts with default configuration
- **THEN** the `steam` user SHALL exist with UID/GID 1000/1000 and a home directory at `/home/steam`

#### Scenario: Data directories exist with correct ownership

- **WHEN** the container starts
- **THEN** all data directories SHALL exist and be owned by the configured identity (see `shared-config`)
