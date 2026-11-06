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

**Game tree directory**:
Path of the Game tree: `/data/gameserver`.
_Avoid_: Mount point, Game directory

**Manifest install**:
Immutable per-version game copy. Never written after download.
_Avoid_: Pristine install, Pristine game

**Manifests directory**:
Path holding every Manifest install: `/data/manifests`.
_Avoid_: Manifests volume, Depot directory

**Mod overlay**:
User-supplied files shadowing the same relative paths in the Game tree.
_Avoid_: Mods, Union layer

**Mod overlay directory**:
Path holding the Mod overlay: `/data/mods`.
_Avoid_: Mods directory, Mod folder

### Configuration

**Base config**:
Whatever is read as merge input: the persisted file when present, else the Example config.
_Avoid_: User config, Saved config

**Generated config**:
Merged output written back to `/data/config/enshrouded_server.json`.
_Avoid_: Output config, New config

**Save directory**:
Directory holding world save data, selected by the Generated config and defaulting to `/data/saves`.
_Avoid_: Save path, Save folder

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

### Lifecycle

**Server lifecycle**:
Ordered startup, supervision, and shutdown of the game server process.
_Avoid_: Server run, Server loop

**PID file**:
File recording the PID of the launched server process; its presence is the restore guard.
_Avoid_: Lock file, Marker

**Player presence**:
Connected-player set derived from the dedicated server's stdout.
_Avoid_: Player list, Roster cache

**Player handle**:
Game-assigned `index(session)` identifier for one connection.
_Avoid_: Player ID, Slot

**Pending join**:
Window opened by a session acceptance or Steam authentication line before a player handle
appears.
_Avoid_: Login timer, Connecting flag

**Session block**:
Periodic stdout block listing the local `m#0` machine and any remote `m#N` machines.
_Avoid_: Status dump, Machine table

**Machine entry**:
One `m#N` row in a Session block; `m#0` is the local baseline and any `N>0` is a remote machine.
_Avoid_: Player count, Peer

**Idle timeout**:
Continuous time with no player presence before Auto Pause suspends the server.
_Avoid_: Player timeout, Empty time

**Auto pause**:
Suspending the whole Wine tree after the idle timeout and resuming it on client traffic.
_Avoid_: Sleep, Hibernate, Shutdown

**Quiet window**:
Interval when Auto Pause blocks scheduled live Backups and non-essential background loops so the
tree can be suspended without work in flight.
_Avoid_: Pause attempt, Exclusion

**Wake traffic**:
Inbound UDP traffic to the query port that resumes a paused server.
_Avoid_: Wake packet, Query packet
