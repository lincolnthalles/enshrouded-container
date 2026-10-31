## Purpose

Pinned, manifest-driven game installs via a self-contained DepotDownloader binary.

## Requirements

### Requirement: DepotDownloader is installed

The container SHALL include a self-contained DepotDownloader binary that runs without a .NET runtime in the final image. The binary SHALL authenticate anonymously with Steam's CDN for depot discovery.

#### Scenario: DepotDownloader binary is present

- **WHEN** `/opt/depotdownloader/DepotDownloader` is executed inside the container
- **THEN** the file SHALL exist and be executable

#### Scenario: DepotDownloader can reach Steam

- **WHEN** DepotDownloader lists depot information for the game
- **THEN** it SHALL authenticate anonymously with Steam's CDN

### Requirement: Version spec resolution

The entrypoint SHALL resolve a Version spec to a Manifest ID via three methods: explicit digits, Steam build ID with `build:` prefix, and the `latest` keyword (newest Manifest by timestamp). A resolved `latest` Manifest ID SHALL be persisted in a control file for offline fallback.

#### Scenario: Explicit Manifest ID

- **WHEN** `VERSION` is set to explicit digits
- **THEN** those digits SHALL be used as the Manifest ID without network resolution

#### Scenario: Build ID resolution

- **WHEN** `VERSION=build:<id>` is set
- **THEN** the Manifest ID whose branch matches the build, or whose value ends with the build, SHALL be used; if none matches and the build value is numeric, the entrypoint SHALL warn and treat the build value itself as a Manifest ID

#### Scenario: Non-numeric build fallback rejected

- **WHEN** `VERSION=build:<id>` is set, no listed Manifest matches, and `<id>` is not numeric
- **THEN** the entrypoint SHALL exit with an error naming the invalid build value instead of using it as a Manifest ID

#### Scenario: Build resolution listing failure

- **WHEN** `VERSION=build:<id>` is set and the manifest listing fails
- **THEN** the entrypoint SHALL exit with code 1 naming the listing failure as the cause instead of treating the build value as a Manifest ID

#### Scenario: Latest resolution and persistence

- **WHEN** `VERSION=latest` (or unset) is set and DepotDownloader reports manifests
- **THEN** the newest Manifest ID SHALL be used and persisted to the control file

#### Scenario: Offline fallback to cached latest

- **WHEN** `VERSION=latest` is set and DepotDownloader reports no manifests, or the listing fails, but the control file contains a cached Manifest ID
- **THEN** the cached Manifest ID SHALL be used with a warning

#### Scenario: No cached latest and empty listing

- **WHEN** `VERSION=latest` is set, the listing reports no manifests, and no cached Manifest ID exists
- **THEN** the entrypoint SHALL exit with code 1 reporting that no manifests were found

#### Scenario: No cached latest and listing fails

- **WHEN** `VERSION=latest` is set, the listing fails, and no cached Manifest ID exists
- **THEN** the entrypoint SHALL exit with code 1 naming the listing failure as the cause

### Requirement: Install ensures Manifest ID present

Install SHALL resolve the Version spec to a Manifest ID and ensure the matching Manifest install exists: skip when the version directory carries the `.installed` marker (unless forced), otherwise Download it. The `.installed` marker SHALL be written only after the server binary is verified present.

#### Scenario: Skip download if version already installed

- **WHEN** the Manifest install directory already exists with the `.installed` marker and no force flag is set
- **THEN** no Download SHALL run

#### Scenario: Marker written only on verified install

- **WHEN** a download completes but the server binary is absent from the Manifest install
- **THEN** the Install SHALL fail and the `.installed` marker SHALL NOT be written

### Requirement: Auth strategy selection

The Download SHALL use exactly one credential strategy, selected by availability: Steam username/password when a username is set; auth-free Manifest file plus depot keys when both exist and support is available; anonymous for `latest` or an empty/unset Version spec when no Manifest file exists; interactive QR login otherwise. When a Manifest file exists without depot keys and no Steam username is set, the Install SHALL fail with an error naming key setup and Steam login as alternatives.

#### Scenario: Auth-free preferred when material present

- **WHEN** no Steam username is configured, and depot keys and the Manifest file for the requested Manifest ID both exist with support available
- **THEN** the Download SHALL use the Manifest file and keys instead of Steam login flags

#### Scenario: Steam auth when credentials set

- **WHEN** a Steam username is set, even when depot keys and the Manifest file exist, or the Manifest file exists without depot keys
- **THEN** the Download SHALL authenticate with the Steam credentials

#### Scenario: Error when manifest exists without keys

- **WHEN** the Manifest file exists for the requested Manifest ID, no depot keys are available, and no Steam username is set
- **THEN** the entrypoint SHALL exit with an error naming key setup and Steam login as alternatives

### Requirement: Unsupported downloader fails fast

When depot keys and the Manifest file exist but the DepotDownloader lacks Manifest-file support and no Steam username is set, the Install SHALL fail with an error naming the Mod fork and Steam login as alternatives, even when the Version spec is `latest`.

#### Scenario: Error when downloader lacks support despite material

- **WHEN** depot keys and the Manifest file exist but the DepotDownloader lacks Manifest-file support and no Steam username is set
- **THEN** the entrypoint SHALL exit with an error naming the Mod fork and Steam login as alternatives, even when the Version spec is `latest`

#### Scenario: Interactive login otherwise

- **WHEN** the requested Manifest ID is not installed, no Manifest file exists, and no credentials are available
- **THEN** the Download SHALL print login instructions and authenticate interactively (anonymous when the Version spec is `latest` or empty)

#### Scenario: Explicit download ID does not use anonymous fallback

- **WHEN** `download <manifest_id>` is invoked with no Manifest file, credentials, or token
- **THEN** the Download SHALL use interactive login instead of the anonymous latest fallback

### Requirement: Install-time guards and immutability

Before Downloading, the Install SHALL verify sufficient disk space accounting for any partial download of the same Manifest ID (see `disk-space-guards`). The Install SHALL reject a symlinked Manifest install directory. A non-numeric Manifest ID SHALL be rejected before any filesystem path is constructed. After a successful Download, the Manifest install SHALL be marked read-only (see `game-tree-rebuild`). An interrupted download SHALL resume within quota on the next attempt.

#### Scenario: Resume partial download within quota

- **WHEN** the same Manifest ID has a partial download and effective free space meets the minimum
- **THEN** the Download SHALL proceed and resume

#### Scenario: Symlinked Manifest install refused

- **WHEN** the Manifest install directory for the requested Manifest ID is a symlink
- **THEN** the Install SHALL fail with an error naming the symlinked directory and SHALL NOT download through it

#### Scenario: Non-numeric Manifest ID rejected

- **WHEN** `download <manifest-id>` is invoked with a non-numeric ID
- **THEN** the command SHALL fail with an error naming the invalid Manifest ID before touching the filesystem

### Requirement: Volume-based version switching

Manifest installs SHALL live on a persistent volume mapped to the manifests directory. Changing the Version spec and restarting the container SHALL switch to the specified Manifest ID without re-downloading previously installed versions.

#### Scenario: Switch between installed versions

- **WHEN** the container is restarted with a different Version spec whose Manifest ID was previously downloaded
- **THEN** the game SHALL use that Manifest install with no download

#### Scenario: Persist game data across container recreation

- **WHEN** the container is removed and recreated with the same manifests volume
- **THEN** all previously downloaded Manifest installs SHALL still be present
