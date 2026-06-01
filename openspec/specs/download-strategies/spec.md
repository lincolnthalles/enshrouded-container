## Requirements

### Requirement: Shared depot download loop

The system SHALL provide a single `download_depots(manifest_id, target_dir, config)` function in `enshctl.download` that iterates discovered depots and runs DepotDownloader for each. Strategy-specific behavior SHALL be controlled by a `DownloadConfig` dataclass.

#### Scenario: Auth-free download

- **WHEN** `download_depots` is called with `DownloadConfig(use_manifestfile=True, depot_keys_path=Path(...), manifest_file=Path(...))`
- **THEN** DepotDownloader SHALL be invoked with `-depotkeys` and `-manifestfile` flags

#### Scenario: Steam auth download

- **WHEN** `download_depots` is called with `DownloadConfig(username="user", password="pass")`
- **THEN** DepotDownloader SHALL be invoked with `-username` and `-password` flags

#### Scenario: Anonymous download

- **WHEN** `download_depots` is called with `DownloadConfig()` (defaults)
- **THEN** DepotDownloader SHALL be invoked with no auth flags

#### Scenario: QR login download

- **WHEN** `download_depots` is called with `DownloadConfig(use_qr=True)`
- **THEN** DepotDownloader SHALL be invoked with `-qr` flag

### Requirement: DownloadConfig dataclass

The system SHALL provide a `DownloadConfig` dataclass in `enshctl.download` with fields for all strategy-specific parameters: `username`, `password`, `use_manifestfile`, `depot_keys_path`, `manifest_file`, `use_qr`. All fields SHALL have sensible defaults (None/False).

#### Scenario: Default config is anonymous

- **WHEN** `DownloadConfig()` is constructed with no arguments
- **THEN** `username` SHALL be `None`, `use_manifestfile` SHALL be `False`, `use_qr` SHALL be `False`

### Requirement: Depot discovery preserved

The system SHALL preserve the `discover_depots()` function in `enshctl.download`. It SHALL return a list of `(depot_id, manifest_id)` tuples by invoking DepotDownloader with `-manifest-only`.

#### Scenario: Multi-depot discovery

- **WHEN** DepotDownloader reports depot keys for depots 2278521 and 2278522
- **THEN** `discover_depots()` SHALL return both depot IDs with their current manifest IDs
