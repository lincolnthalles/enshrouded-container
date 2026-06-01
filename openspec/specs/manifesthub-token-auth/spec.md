### Requirement: Depot keys generation from external source

A `depot.keys` file SHALL be generated at `/data/manifests/depot.keys` containing depot decryption keys in the format `depotId;hexKey` per line. The file SHALL be generated from a user-supplied git repository URL or fallback to archive.org mirrors. Generation SHALL only occur if the file does not already exist.

#### Scenario: Generate depot.keys from git repo

- **WHEN** `DEPOT_KEYS_REPO` is set to a git-compatible URL (e.g., `https://github.com/user/repo`)
- **THEN** the orchestrator SHALL fetch `key.vdf` from that repo (auto-inferring branch and path) and parse it into `depot.keys`

#### Scenario: Generate depot.keys from archive.org fallback

- **WHEN** `DEPOT_KEYS_REPO` is not set
- **THEN** the orchestrator SHALL fetch `key.vdf` from `https://archive.org/download/manifest-hub-repo/NEW-depot-keys.zip/` and parse it into `depot.keys`

#### Scenario: Skip generation if depot.keys exists

- **WHEN** `/data/manifests/depot.keys` already exists
- **THEN** the orchestrator SHALL NOT regenerate it

#### Scenario: Error on key generation failure

- **WHEN** both git repo and archive.org sources fail to provide a valid `key.vdf`
- **THEN** the orchestrator SHALL raise an error with a clear message indicating the failure and suggesting the user supply a `DEPOT_KEYS_REPO` or `STEAM_PASSWORD`, or source a key file elsewhere and save it as /data/manifests/depot.keys.

### Requirement: ManifestHub manifest fetching

When a `MANIFESTHUB_API_TOKEN` is provided, the orchestrator SHALL download missing `.manifest` files from the ManifestHub API. The API endpoint is `https://api.manifesthub1.filegear-sg.me/manifest?apikey={token}&depotid={depotId}&manifestid={manifestId}`, overridable via `MANIFESTHUB_API_URL` env var.

#### Scenario: Download manifest for specific version

- **WHEN** `MANIFESTHUB_API_TOKEN` is set and a `.manifest` file for the requested version does not exist at `/data/manifests/{depotId}_{manifestId}.manifest`
- **THEN** the orchestrator SHALL download it from ManifestHub and save it to `/data/manifests/{depotId}_{manifestId}.manifest`

#### Scenario: Skip download if manifest exists

- **WHEN** the `.manifest` file already exists at `/data/manifests/{depotId}_{manifestId}.manifest`
- **THEN** the orchestrator SHALL NOT re-download it

#### Scenario: ManifestHub API error

- **WHEN** the ManifestHub API returns a non-success HTTP status or JSON error
- **THEN** the orchestrator SHALL raise an error with the API response details

### Requirement: ManifestHub API URL override

The ManifestHub API base URL SHALL be overridable via the `MANIFESTHUB_API_URL` env var. If not set, the default SHALL be `https://api.manifesthub1.filegear-sg.me`.

#### Scenario: Custom API URL

- **WHEN** `MANIFESTHUB_API_URL` is set (e.g., `https://my-mirror.example.com`)
- **THEN** manifest downloads SHALL use that URL as the base (e.g., `https://my-mirror.example.com/manifest?apikey=...`)

#### Scenario: Default API URL

- **WHEN** `MANIFESTHUB_API_URL` is not set
- **THEN** the default `https://api.manifesthub1.filegear-sg.me` SHALL be used

### Requirement: Auth-free DepotDownloader invocation

When `depot.keys` and the required `.manifest` file exist, DepotDownloader SHALL be invoked with `-depotkeys` and `-manifestfile` flags for auth-free download from Steam's CDN.

#### Scenario: Download with depot.keys and manifest file

- **WHEN** `/data/manifests/depot.keys` exists and the `.manifest` file for the requested version exists
- **THEN** DepotDownloader SHALL be invoked with `-depotkeys /data/manifests/depot.keys -manifestfile /data/manifests/{depotId}_{manifestId}.manifest` instead of `-username`/`-password` flags

#### Scenario: Fallback to Steam login when keys missing

- **WHEN** `depot.keys` does not exist and `STEAM_USERNAME`/`STEAM_PASSWORD` are provided
- **THEN** DepotDownloader SHALL be invoked with `-username`/`-password` flags as in the current behavior

### Requirement: DepotDownloaderMod feature detection

The orchestrator SHALL detect whether the installed DepotDownloader supports `-manifestfile`/`-depotkeys` flags. If unsupported, a clear error SHALL be raised.

#### Scenario: DepotDownloaderMod supports manifest flags

- **WHEN** DepotDownloader is invoked with `-manifestfile /dev/null -depotkeys /dev/null` and stderr does not contain "unknown" or "unrecognized" flag errors
- **THEN** the orchestrator SHALL proceed with auth-free download

#### Scenario: Vanilla DepotDownloader detected

- **WHEN** DepotDownloader is invoked with `-manifestfile /dev/null -depotkeys /dev/null` and stderr contains "unknown option" or "unrecognized argument"
- **THEN** the orchestrator SHALL raise an error: "This container was built with vanilla DepotDownloader which does not support auth-free downloads. Use the DepotDownloaderMod fork or provide STEAM_USERNAME/STEAM_PASSWORD."

### Requirement: Manifest listing via DepotDownloader

When `MANIFESTHUB_API_TOKEN` is provided, the orchestrator SHALL call DepotDownloader with `-manifest-only` to discover all available manifest IDs for the app. This list drives which `.manifest` files to fetch from ManifestHub.

#### Scenario: List manifests with token

- **WHEN** `MANIFESTHUB_API_TOKEN` is set
- **THEN** the orchestrator SHALL call DepotDownloader `-app 2278520 -depot 2278521 -manifest-only -os windows` and parse the output for manifest IDs

#### Scenario: Manifest listing fails

- **WHEN** DepotDownloader fails to list manifests (e.g., Steam CDN unreachable)
- **THEN** the orchestrator SHALL raise an error with the DepotDownloader output

### Requirement: Graceful error for missing download path

If an old version is not installed, no manifest file exists, and the user is not supplying a password or token, the orchestrator SHALL raise a clear error explaining the options.

#### Scenario: No path available for old version

- **WHEN** the requested version is not installed, no `.manifest` file exists, `STEAM_PASSWORD` is not set, and `MANIFESTHUB_API_TOKEN` is not set
- **THEN** the orchestrator SHALL exit with error: "Version {manifest_id} is not installed and cannot be downloaded. Provide STEAM_PASSWORD for Steam login, or MANIFESTHUB_API_TOKEN for ManifestHub access, or use VERSION=latest."
