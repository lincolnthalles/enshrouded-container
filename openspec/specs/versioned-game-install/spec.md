## Requirements

### Requirement: DepotDownloader is installed

The container SHALL include DepotDownloader (either the dd fork or upstream) built as a self-contained trimmed single-file binary at `/opt/depotdownloader/DepotDownloader`. The binary SHALL be built from source in a Docker builder stage. The repository URL SHALL be configurable via the `DD_REPO_URL` build argument. The builder stage SHALL produce a binary named `DepotDownloader` regardless of which repository is used.

#### Scenario: DepotDownloader binary is present

- **WHEN** `ls /opt/depotdownloader/DepotDownloader` is executed inside the container
- **THEN** the file SHALL exist and be executable

#### Scenario: DepotDownloader can authenticate

- **WHEN** DepotDownloader is invoked with `-app 2278520`
- **THEN** it SHALL authenticate anonymously with Steam's CDN and list depot information

#### Scenario: dd repository URL is configurable

- **WHEN** the image is built with `--build-arg DD_REPO_URL=https://github.com/example/dd-fork.git`
- **THEN** the binary SHALL be built from that repository instead of the default

#### Scenario: No .NET runtime in final image

- **WHEN** the final image is inspected
- **THEN** no .NET runtime packages (`dotnet-runtime-*`) SHALL be installed

### Requirement: Download orchestration

The `download_version` function in `enshctl.install` SHALL delegate the actual DepotDownloader invocation to `enshctl.download.download_depots()`. The four `_download_version_*` functions SHALL be removed from `install.py`. The `download_version` function SHALL construct a `DownloadConfig` based on available credentials and pass it to `download_depots()`.

#### Scenario: Auth-free path uses download_depots

- **WHEN** depot keys and manifest file exist and DepotDownloader supports `-manifestfile`
- **THEN** `download_version` SHALL call `download_depots(mid, dir, DownloadConfig(use_manifestfile=True, depot_keys_path=..., manifest_file=...))`

#### Scenario: Steam auth path uses download_depots

- **WHEN** `STEAM_USERNAME` and `STEAM_PASSWORD` are set
- **THEN** `download_version` SHALL call `download_depots(mid, dir, DownloadConfig(username=..., password=...))`

#### Scenario: No duplicated depot iteration

- **WHEN** the codebase is scanned for the depot iteration pattern (loop over `_discover_depots()` + subprocess.run)
- **THEN** it SHALL appear only in `enshctl/download.py`

### Requirement: Game download to versioned path

The game server SHALL be downloaded to `/data/manifests/<manifest_id>/` where `<manifest_id>` is the Steam depot manifest ID. The Enshrouded Windows dedicated server binary SHALL reside at `/data/manifests/<manifest_id>/enshrouded_server.exe`. Downloaded directories SHALL be treated as immutable — the entrypoint SHALL NOT write to them after download. The download SHALL use one of two methods: (1) auth-free via `depot.keys` + `.manifest` file, or (2) Steam login via username/password. If neither method is available for an old version, the system SHALL raise a clear error. Before downloading, the system SHALL check disk space (see `disk-space-guards` capability).

#### Scenario: Download with explicit manifest ID

- **WHEN** `VERSION=1234567890123456789` is set and the container starts
- **THEN** the game SHALL be downloaded to `/data/manifests/1234567890123456789/` using `DepotDownloader -app 2278520 -depot 2278521 -manifest 1234567890123456789 -os windows`

#### Scenario: Download latest version

- **WHEN** `VERSION=latest` (or unset) and the container starts
- **THEN** the latest available manifest SHALL be resolved, and the game SHALL be downloaded to `/data/manifests/<latest_manifest_id>/`

#### Scenario: Skip download if version already installed

- **WHEN** the target version directory already exists and contains the `.installed` marker file (created only when DepotDownloader exits with code 0)
- **THEN** the download SHALL be skipped

#### Scenario: Download with auth-free depot.keys and manifest

- **WHEN** `depot.keys` exists and the `.manifest` file for the requested version exists
- **THEN** DepotDownloader SHALL be invoked with `-depotkeys /data/manifests/depot.keys -manifestfile /data/manifests/{depotId}_{manifestId}.manifest` instead of Steam login flags

#### Scenario: Error when no download method available

- **WHEN** the requested version is not installed, no `.manifest` file exists, `STEAM_PASSWORD` is not set, and no manifest token is available
- **THEN** the orchestrator SHALL exit with error: "Version {manifest_id} is not installed and cannot be downloaded. Provide STEAM_PASSWORD for Steam login, or use VERSION=latest."

#### Scenario: Abort on insufficient disk space

- **WHEN** `effective_free = free + partial_download_size < INSTALL_MIN_FREE_SPACE` for the target manifest
- **THEN** the system SHALL log an error with exact sizes and exit with code 1

#### Scenario: Resume partial download within quota

- **WHEN** the same manifest has a partial download directory and `effective_free >= INSTALL_MIN_FREE_SPACE`
- **THEN** the download SHALL proceed (DepotDownloader will validate and resume)

### Requirement: Manifest resolution

The entrypoint SHALL support resolving versions via three methods: explicit manifest ID, Steam build ID with `build:` prefix, and `latest` keyword. Manifest metadata SHALL be persisted in `/data/manifests/versions.json` for audit.

#### Scenario: Resolve build ID to manifest

- **WHEN** `VERSION=build:16789000` is set
- **THEN** the entrypoint SHALL query DepotDownloader for manifests matching build 16789000 and download the corresponding depot

#### Scenario: Persist version metadata

- **WHEN** a game version is downloaded
- **THEN** `/data/manifests/versions.json` SHALL be updated with an entry containing manifest ID, build ID, download timestamp, and branch name

### Requirement: install.py size reduction

The `enshctl/install.py` module SHALL be reduced from approximately 701 lines to approximately 400 lines by moving download strategy code to `enshctl/download.py`. The module SHALL retain: version resolution, manifest management, key fetching, and the `ensure_install` orchestration function.

#### Scenario: install.py focused on manifest management

- **WHEN** `enshctl/install.py` is analyzed
- **THEN** it SHALL contain version resolution (`resolve_manifest`), manifest fetching (`fetch_manifests`, `prepare_manifests`), key management (`ensure_depot_keys`, `parse_key_vdf`), and install orchestration (`ensure_install`, `download_version`)

#### Scenario: Download logic in download.py

- **WHEN** `enshctl/download.py` is analyzed
- **THEN** it SHALL contain `DownloadConfig`, `download_depots()`, and `discover_depots()`

### Requirement: Volume-based version switching

The game server data SHALL be stored on a named Docker volume `gameserver` mapped to `/data/manifests`. Changing the `VERSION` env var and restarting the container SHALL switch to the specified version without re-downloading previously installed versions.

#### Scenario: Switch between installed versions

- **WHEN** `VERSION=manifest_a` was used, then the container is restarted with `VERSION=manifest_b` (and manifest_b was previously downloaded)
- **THEN** the game SHALL use `/data/manifests/manifest_b/` as the active version via the symlink tree, with no download

#### Scenario: Persist game data across container recreation

- **WHEN** the container is removed and recreated with the same `gameserver` volume
- **THEN** all previously downloaded versions SHALL still be present
