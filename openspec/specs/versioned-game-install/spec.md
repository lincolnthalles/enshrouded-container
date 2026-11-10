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

The entrypoint SHALL resolve a Version spec to a Manifest ID via three methods: explicit digits, Steam build ID with `build:` prefix, and the `latest` keyword (newest Manifest by timestamp; also used for an empty or unset `VERSION`). A resolved `latest` Manifest ID and its timestamp SHALL be persisted in a control file in the Manifests directory for offline fallback.

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

- **WHEN** `VERSION` is `latest`, empty, or unset and DepotDownloader reports manifests
- **THEN** the newest Manifest ID and its timestamp SHALL be used and persisted to the control file

#### Scenario: Offline fallback to cached latest

- **WHEN** `VERSION` is `latest`, empty, or unset and DepotDownloader reports no manifests, or the listing fails, but the control file contains a cached Manifest ID
- **THEN** the cached Manifest ID SHALL be used with a warning

#### Scenario: No cached latest and empty listing

- **WHEN** `VERSION` is `latest`, empty, or unset, the listing reports no manifests, and no cached Manifest ID exists
- **THEN** the entrypoint SHALL exit with code 1 reporting that no manifests were found

#### Scenario: No cached latest and listing fails

- **WHEN** `VERSION` is `latest`, empty, or unset, the listing fails, and no cached Manifest ID exists
- **THEN** the entrypoint SHALL exit with code 1 naming the listing failure as the cause

### Requirement: Latest candidate lookup without install

An update check SHALL select the newest listed Manifest by timestamp without installing it or
replacing the cached latest Manifest. A successful Auto Update install SHALL replace the cached
latest Manifest with the installed Manifest ID and timestamp; a failed Auto Update download or
install SHALL leave the cache unchanged.

#### Scenario: Update check does not rewrite the cache

- **WHEN** an update check finds a different Manifest
- **THEN** the cached latest Manifest SHALL remain unchanged until the install succeeds

#### Scenario: Successful Auto Update install records the candidate

- **WHEN** the Manifest install for an Auto Update candidate completes
- **THEN** the cached latest Manifest SHALL be replaced with that Manifest ID and timestamp

#### Scenario: Failed Auto Update install keeps the cache

- **WHEN** the Auto Update download or install fails
- **THEN** the cached latest Manifest SHALL remain unchanged

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
- **THEN** the Download SHALL print login instructions and authenticate interactively (anonymous when the Version spec is `latest`, empty, or unset)

#### Scenario: Explicit download ID does not use anonymous fallback

- **WHEN** `download <manifest_id>` is invoked with no Manifest file, credentials, or token
- **THEN** the Download SHALL use interactive login instead of the anonymous latest fallback

### Requirement: Install-time guards and immutability

Before Downloading, the Install SHALL verify sufficient disk space (see `disk-space-guards`). The Install SHALL reject a symlinked Manifest install directory. A non-numeric Manifest ID SHALL be rejected before any filesystem path is constructed. After a successful Download, the Manifest install SHALL be marked read-only (see `game-tree-rebuild`). An interrupted download SHALL resume within quota on the next attempt.

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

Manifest installs SHALL live on a persistent volume mapped to the manifests directory. Changing the
Version spec and restarting the container SHALL switch to the specified Manifest ID without
re-downloading when that Complete Manifest install is still present.

#### Scenario: Switch between installed versions

- **WHEN** the container is restarted with a different Version spec whose Complete Manifest install is
  still present
- **THEN** the game SHALL use that Manifest install with no download

#### Scenario: Persist game data across container recreation

- **WHEN** the container is removed and recreated with the same manifests volume and
  `MANIFEST_PRUNE_ENABLED=false`
- **THEN** every Manifest install on the volume SHALL remain present

### Requirement: Latest-tracking Manifest pruning

After a start or Auto Update restart prepares the Active Manifest install and Game tree, when the
Version spec is `latest`, empty, or unset and Manifest pruning is enabled, the container SHALL retain
the Active Manifest install and the Previous Active Manifest install and SHALL stage every other
complete Manifest install in the Manifests directory under `.prune` for deletion.

#### Scenario: Update restart keeps the rollback target

- **WHEN** Auto Update restarts into a new Manifest
- **THEN** the new Manifest install and the previously active Manifest install SHALL remain
- **AND** every complete Manifest install other than those two SHALL be staged under `.prune` for
  deletion

#### Scenario: First start prunes an existing backlog

- **WHEN** a latest-tracking deployment starts with more than two complete Manifest installs and no
  distinct recorded previous install
- **THEN** the Active Manifest install and the most recently completed other install SHALL remain
- **AND** the remaining complete Manifest installs SHALL be staged under `.prune` for deletion

### Requirement: Activation record

The container SHALL store the activation record in `.manifest-history` in the Manifests directory. It
SHALL contain the current Active Manifest and, when one exists, the most recent distinct Manifest that
was Active before it; the previous entry SHALL never equal the Active Manifest. When the Active
Manifest changes, the previous entry SHALL become the Manifest that was Active before the change.

#### Scenario: Activation record survives recreation

- **WHEN** the container is removed and recreated with the same manifests volume
- **THEN** the next start SHALL select the same Previous Active Manifest as the rollback target

#### Scenario: Recorded previous install is retained

- **WHEN** the activation record names a distinct, complete install
- **THEN** that install SHALL remain as the Previous Active Manifest
- **AND** older complete installs SHALL be staged under `.prune` for deletion

### Requirement: Activation record update

The activation record SHALL update only after the Active Manifest install and Game tree are prepared
successfully on container start or an Auto Update restart. It SHALL update before the Previous Active
Manifest is selected for pruning. `enshctl install` and `enshctl download` SHALL NOT write the
record. A failed preparation SHALL leave the record unchanged.

#### Scenario: Failed preparation keeps the record

- **WHEN** preparing the Active Manifest install or Game tree fails
- **THEN** the activation record SHALL remain unchanged
- **AND** the Active, Previous Active, and requested Manifest installs SHALL remain

### Requirement: Activation record write failure

When the activation record cannot be replaced after successful preparation, the container SHALL warn
and SHALL NOT run post-activation Manifest pruning during that start.

#### Scenario: Record write failure skips pruning

- **WHEN** the activation record cannot be replaced
- **THEN** a warning SHALL describe the failure
- **AND** post-activation Manifest pruning SHALL NOT run

### Requirement: Activation record integrity

The activation record SHALL be replaced atomically. An unreadable or malformed record SHALL be
treated as absent. The fallback SHALL still select a rollback target, and pruning SHALL continue.

#### Scenario: Malformed record falls back

- **WHEN** the activation record is unreadable or malformed
- **THEN** the fallback SHALL select the rollback target
- **AND** pruning SHALL continue

### Requirement: Previous Active Manifest fallback

When the record has no distinct previous install, or the recorded previous install is absent or
incomplete, the fallback SHALL be the other complete Manifest install whose `.installed` marker was
written most recently, excluding the Active Manifest install. Ties SHALL be broken by the greatest
Manifest ID compared as an exact integer. When no other complete Manifest install exists, only the
Active Manifest install SHALL be retained.

#### Scenario: Previous install is missing

- **WHEN** the recorded Previous Active Manifest install is absent or incomplete and another
  complete Manifest install exists
- **THEN** the most recently completed other install SHALL remain as the rollback target
- **AND** older complete installs SHALL be staged under `.prune` for deletion

### Requirement: Manifest pruning scope and opt-out

A pinned Version spec (`build:` or explicit digits) SHALL retain every Manifest install.
`MANIFEST_PRUNE_ENABLED` SHALL default to true, including when unset or not a recognized boolean. A
recognized false value (`false`, `0`, `off`, `no`) SHALL disable new pruning and reclamation; a
recognized true value (`true`, `1`, `on`, `yes`) SHALL enable them; values SHALL match
case-insensitively after trimming whitespace. Cleanup of already-staged `.prune` contents SHALL still
run.

#### Scenario: Pinned version keeps every install

- **WHEN** the Version spec is an explicit Manifest ID or `build:<id>`
- **THEN** no Manifest install SHALL be deleted

#### Scenario: Opt-out keeps every install

- **WHEN** `MANIFEST_PRUNE_ENABLED=false`
- **THEN** no Manifest install SHALL be deleted

#### Scenario: Invalid opt-out uses the default

- **WHEN** `MANIFEST_PRUNE_ENABLED` is not a recognized boolean
- **THEN** Manifest install deletion SHALL use the default of enabled

### Requirement: Manifest reclamation before install

Before a latest-tracking Download with Manifest pruning enabled, the container SHALL evaluate free
space against the Install minimum (see `disk-space-guards`). When the Install disk-space check would
fail, the container SHALL reclaim complete installs outside the reclamation keep set. Reclamation
SHALL delete staged contents before the Install disk-space check is re-evaluated. Reclamation SHALL
NOT change the activation record.

#### Scenario: Disk-full backlog is reclaimed

- **WHEN** the initial free-space evaluation fails and complete installs outside the reclamation keep
  set exist
- **THEN** reclamation SHALL delete them before the Install disk-space check
- **AND** the Download SHALL proceed when the re-evaluated check meets the minimum

#### Scenario: No reclamation when space is sufficient

- **WHEN** the initial free-space evaluation passes
- **THEN** no Manifest install SHALL be deleted before the Download

#### Scenario: Disabled reclamation keeps every install

- **WHEN** the Version spec is pinned or `MANIFEST_PRUNE_ENABLED` is a recognized false value
- **THEN** no Manifest install SHALL be deleted before the Download

### Requirement: Reclamation keep set

The reclamation keep set SHALL be the requested Manifest install, the recorded Active Manifest
install, every Manifest install backing the current Game tree when present, and the recorded Previous
Active install when complete. The requested Manifest install SHALL never be reclaimed.

#### Scenario: Requested Manifest is never reclaimed

- **WHEN** the requested Manifest install is complete but outside the recorded keep set
- **THEN** it SHALL remain

#### Scenario: Ambiguous Game tree keeps every linked install

- **WHEN** the Game tree links multiple Manifest installs
- **THEN** every linked Manifest install SHALL remain

### Requirement: Reclamation fallback keep install

When no complete recorded previous exists, the reclamation keep set SHALL also include the other
complete Manifest install whose `.installed` marker was written most recently, excluding the
requested Manifest install, the recorded Active Manifest install, and every Manifest install backing
the current Game tree when present. Ties SHALL be broken by the greatest Manifest ID compared as an
exact integer.

#### Scenario: First start keeps a fallback

- **WHEN** no Active Manifest is recorded and the initial free-space evaluation fails
- **THEN** the requested Manifest and the most recently completed other install SHALL remain
- **AND** other complete installs outside the reclamation keep set SHALL be reclaimed

### Requirement: Manifest install deletion candidates

Only numeric directories carrying the `.installed` marker are deletion candidates. An incomplete
Manifest install SHALL be skipped with a warning.

#### Scenario: Incomplete install survives

- **WHEN** a numeric Manifest directory lacks the `.installed` marker
- **THEN** it SHALL remain
- **AND** a warning SHALL name it

### Requirement: Manifest install deletion protected entries

Entries directly in the Manifests directory—`.manifest` files, `depot.keys`, the latest control file,
`.manifest-history`, symbolic links, and every other non-numeric entry—SHALL never be deleted. Files
and links inside a deleted Manifest install or under `.prune` are not protected entries.

#### Scenario: Snapshot and control material is untouched

- **WHEN** Manifest installs are deleted
- **THEN** every `.manifest` file, `depot.keys`, the latest control file, and `.manifest-history` in
  the Manifests directory SHALL remain

#### Scenario: Non-install entries are untouched

- **WHEN** a non-numeric entry or a symbolic link exists directly in the Manifests directory
- **THEN** it SHALL remain

### Requirement: Manifest install deletion staging

Every Manifest install deleted by pruning or reclamation SHALL be renamed under a `.prune` real
directory in the Manifests directory before its contents are deleted. The container SHALL create
`.prune` as a real directory when absent. It SHALL NOT follow, delete, or replace a symlinked or other
non-directory `.prune`; it SHALL skip deletion with a warning. An interrupted deletion SHALL NOT leave
a partially deleted directory at a Manifest install path.

#### Scenario: Interrupted deletion is safe

- **WHEN** the container stops during Manifest install deletion
- **THEN** no partially deleted directory SHALL remain at a Manifest install path

#### Scenario: Symlinked staging is not followed

- **WHEN** `.prune` is a symbolic link or other non-directory
- **THEN** Manifest install deletion SHALL be skipped with a warning
- **AND** `.prune` and any link target SHALL remain

### Requirement: Manifest pruning cleanup

At container start, and before each Download's initial free-space evaluation, the container SHALL
remove the contents of `.prune` regardless of Version spec or `MANIFEST_PRUNE_ENABLED`, leaving
`.prune` itself in place. Symbolic links inside `.prune` SHALL be unlinked without following them. A
symlinked or other non-directory `.prune` SHALL be skipped with a warning without following it or
changing its target.

#### Scenario: Cleanup runs while pruning is disabled

- **WHEN** `MANIFEST_PRUNE_ENABLED=false` and `.prune` contains pruned data
- **THEN** the next container start SHALL remove that data
- **AND** no other Manifest install SHALL be deleted

#### Scenario: Cleanup precedes the disk evaluation

- **WHEN** staged `.prune` data exists and a Download is about to start
- **THEN** cleanup SHALL complete before the initial free-space evaluation

#### Scenario: Cleanup does not follow staging

- **WHEN** `.prune` is a symbolic link at container start
- **THEN** cleanup SHALL be skipped with a warning
- **AND** the link target SHALL remain

### Requirement: Manifest pruning background deletion

Post-activation Manifest pruning SHALL delete in the background and SHALL NOT delay server start or
Auto Update relaunch.

#### Scenario: Restart does not wait for deletion

- **WHEN** a start or Auto Update restart stages Manifest installs for pruning
- **THEN** the server SHALL start without waiting for their bytes to be reclaimed

### Requirement: Manifest pruning failure isolation

A post-activation pruning failure SHALL warn and SHALL NOT prevent the server from starting. A
reclamation failure SHALL warn and proceed to the re-evaluated Install disk-space check, following
`disk-space-guards` when space remains insufficient.

#### Scenario: Pruning failure does not block start

- **WHEN** a Manifest install cannot be deleted during post-activation pruning
- **THEN** a warning SHALL describe it
- **AND** the server SHALL continue starting

#### Scenario: Reclamation failure follows the disk check

- **WHEN** reclamation cannot delete a Manifest install
- **THEN** a warning SHALL describe it
- **AND** the re-evaluated Install disk-space check SHALL decide whether the Download proceeds
