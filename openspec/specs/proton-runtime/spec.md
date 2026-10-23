## Purpose

Plain-Wine game execution environment: launch, prefix lifecycle, and version reporting.

## Requirements

### Requirement: Wine server launch

The game SHALL be launched under Wine wrapped in a virtual display server, running as the `steam` user with the Game tree as its working directory. The server environment SHALL carry the Wine prefix, architecture, debug, and resolved DLL override settings (see `server-lifecycle` for startup ordering and environment rules).

#### Scenario: Server launches under Wine

- **WHEN** the server process is started
- **THEN** the game executable SHALL run under Wine in a virtual display as the `steam` user

#### Scenario: Wine environment is set during server launch

- **WHEN** the server process is started
- **THEN** its environment SHALL contain the Wine prefix path and the resolved DLL overrides

### Requirement: Machine ID generation

The image SHALL generate `/etc/machine-id` from the kernel UUID during the image build.

#### Scenario: Machine ID exists at runtime

- **WHEN** the container starts
- **THEN** `/etc/machine-id` SHALL exist and contain a valid UUID

### Requirement: Wine prefix lifecycle

The Wine prefix SHALL be created on first start via prefix initialization running as the `steam` user under the virtual display, marked complete afterwards, and reused on later starts. Initialization failure SHALL fail startup.

#### Scenario: Wine prefix is initialized

- **WHEN** the container starts and no completed-initialization marker exists
- **THEN** prefix initialization SHALL run as the `steam` user under the virtual display

#### Scenario: Wine prefix is reused once initialized

- **WHEN** the container starts and the initialization marker exists
- **THEN** prefix initialization SHALL be skipped

#### Scenario: Prefix initialization failure fails startup

- **WHEN** prefix initialization fails or times out
- **THEN** the container SHALL fail startup with the initialization error

### Requirement: Version reporting

The `version-info` invocation SHALL report each installed Manifest ID with its install timestamp. With no installs present, it SHALL report that none are installed.

#### Scenario: Version info lists installed manifests

- **WHEN** `version-info` is run with Manifest installs present
- **THEN** the output SHALL list each installed Manifest ID with its install timestamp

#### Scenario: Version info with no installs

- **WHEN** `version-info` is run with no Manifest installs present
- **THEN** the output SHALL report that no versions are installed

### Requirement: Wine server cleanup on shutdown

After the game server process exits, the shutdown sequence SHALL stop the Wine server process (escalating on timeout) before completing shutdown (see `backup-system` for the full shutdown order).

#### Scenario: Wine server is cleaned up on shutdown

- **WHEN** the container shuts down after the game server exits
- **THEN** the Wine server SHALL be stopped before shutdown completes
