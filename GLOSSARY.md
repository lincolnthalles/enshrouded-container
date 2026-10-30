# Enshctl

Container and CLI that runs a version-pinned Enshrouded dedicated game server with mod support and automated backups.

## Language

### Versioning

**Version spec**:
Raw `VERSION` input selecting which game release to run: `latest`, `build:<id>`, or explicit digits.
_Avoid_: Version, Manifest ID

**Manifest ID**:
Resolved numeric identifier of the Steam depot manifest selected by a Version spec.
_Avoid_: Version, Build ID

**Manifest**:
Steam's file list for a depot at a given release, identified by a Manifest ID.
_Avoid_: Manifest file

**Manifest file**:
`.manifest` artifact consumed for auth-free downloads alongside `depot.keys`.
_Avoid_: Manifest

### Backups

**Backup**:
Stored copy of world save data carrying a Backup name, with its metadata.
_Avoid_: Snapshot, Archive, Backup file

**Backup name**:
Filename identifying a Backup by timestamp, optional Category suffix, and format extension.
_Avoid_: Archive name

**Category**:
Storage location of a Backup: `live`, `cold`, or `emergency`.
_Avoid_: Type, Trigger

**Trigger**:
Event causing a Backup: scheduler tick, SIGTERM shutdown, unexpected crash, or manual invocation. Orthogonal to Category.
_Avoid_: Category

### Game tree

**Game tree**:
Live server directory, rebuilt on every start from a Manifest install plus Mod overlay.
_Avoid_: Mount point, Mount, Overlay

**Manifest install**:
Immutable per-version game copy. Never written after download.
_Avoid_: Pristine install, Pristine game

**Mod overlay**:
User-supplied files shadowing the same relative paths in the Game tree.
_Avoid_: Mods, Union layer

### Configuration

**Base config**:
Whatever is read as merge input: the persisted file when present, else the Example config.
_Avoid_: User config, Saved config

**Generated config**:
Merged output written back to `/data/config/enshrouded_server.json`.
_Avoid_: Output config, New config

**Example config**:
Pristine template shipped in the Manifest install.
_Avoid_: Default config, Game default

### Acquisition

**Install**:
Ensuring a Manifest ID is present: resolve Version spec, skip if present, fetch otherwise.
_Avoid_: Download

**Download**:
Fetching depot bytes via DepotDownloader.
_Avoid_: Install
