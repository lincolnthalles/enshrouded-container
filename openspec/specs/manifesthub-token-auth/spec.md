## Purpose

Auth-free Install inputs: depot decryption keys and Manifest files from external sources. Credential strategy selection lives in `versioned-game-install`; Download execution in `download-strategies`. Auth-free setup runs as part of `start`, `download`, and `install`.

## Requirements

### Requirement: Depot keys from external source

As part of auth-free setup (`MANIFESTHUB_API_TOKEN` or `DEPOT_KEYS_REPO` configured, and Manifest file inputs supported), when no `depot.keys` file exists at `/data/manifests/depot.keys`, the Install SHALL fetch decryption keys from the `DEPOT_KEYS_REPO` git repository, falling back to archive.org mirrors when the repo is unconfigured or its fetch fails, and write them as `depotId;hexKey` lines. An existing file SHALL never be regenerated. When all sources fail, the Install SHALL fail with an error naming key setup and Steam login as alternatives.

#### Scenario: Keys fetched from git repo

- **WHEN** auth-free setup runs with `DEPOT_KEYS_REPO` configured and no `depot.keys` file exists
- **THEN** the key material SHALL be fetched from that repo (auto-inferring branch and path) and written as `depot.keys`

#### Scenario: Keys fetched from archive.org fallback

- **WHEN** auth-free setup runs with no `DEPOT_KEYS_REPO` configured, or the repo fetch fails, and no `depot.keys` file exists
- **THEN** the key material SHALL be fetched from the archive.org mirror and written as `depot.keys`

#### Scenario: Existing keys never regenerated

- **WHEN** a `depot.keys` file already exists
- **THEN** no fetch SHALL run

#### Scenario: All key sources fail

- **WHEN** both the git repo and archive.org sources fail to provide valid key material
- **THEN** the Install SHALL fail with an error naming key setup and Steam login as alternatives

### Requirement: Manifest files from ManifestHub

As part of auth-free setup, the Install SHALL discover available Manifest IDs via the DepotDownloader listing and download each missing Manifest file from the ManifestHub API (`MANIFESTHUB_API_TOKEN` plus `MANIFESTHUB_API_URL`); an empty listing SHALL warn and skip prefetching. ManifestHub API errors SHALL be logged with the API's reported details without aborting the Install; the absent Manifest file then falls through to strategy selection (see `versioned-game-install`). A token without a URL SHALL fail fast directing the user to set `MANIFESTHUB_API_URL`.

#### Scenario: Missing Manifest files prefetched

- **WHEN** auth-free setup runs with `MANIFESTHUB_API_TOKEN` and `MANIFESTHUB_API_URL` configured and the listing reports Manifest IDs
- **THEN** each missing Manifest file SHALL be downloaded from the ManifestHub API and present ones skipped

#### Scenario: Empty listing warns and skips

- **WHEN** auth-free setup runs and the listing reports no Manifest IDs
- **THEN** a warning SHALL be logged and prefetching SHALL be skipped

#### Scenario: ManifestHub API error logged without abort

- **WHEN** the ManifestHub API returns an error for a Manifest file
- **THEN** the error SHALL be logged with the API's reported details and fetching SHALL continue

#### Scenario: Token without URL fails fast

- **WHEN** `MANIFESTHUB_API_TOKEN` is set without `MANIFESTHUB_API_URL`
- **THEN** the Install SHALL fail with an error directing the user to set `MANIFESTHUB_API_URL`

### Requirement: Mod-fork DepotDownloader detection

The Install SHALL detect whether the installed DepotDownloader supports Manifest file inputs by invoking it with no arguments and checking its usage text for the Manifest file flags: the Mod fork documents them, vanilla does not. The probe SHALL touch neither the network nor the working directory. When support is absent and auth-free inputs are requested, the Install SHALL warn and fall back to Steam login when available (see `versioned-game-install` for strategy selection).

#### Scenario: Mod fork detected

- **WHEN** DepotDownloader usage documents the Manifest file flags
- **THEN** Manifest file inputs SHALL be available for strategy selection

#### Scenario: Vanilla DepotDownloader falls back

- **WHEN** DepotDownloader usage lacks the Manifest file flags and auth-free inputs are requested
- **THEN** a warning SHALL be logged and Steam login SHALL be used when credentials are available

#### Scenario: Probe timeout presumes support

- **WHEN** the support probe itself times out
- **THEN** support SHALL be presumed and the warning SHALL note the timeout, rather than blocking the Install
