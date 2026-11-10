# Enshctl

Container and CLI that runs a version-pinned Enshrouded dedicated game server with mod support and automated backups.

## Language

### Versioning

**Version spec**:
Raw `VERSION` input selecting which game release to run: `latest`, `build:<id>`, or explicit digits.
An empty or unset value means `latest`.
_Avoid_: Version, Manifest ID

**Latest-tracking deployment**:
Deployment whose Version spec is `latest`, empty, or unset; governed by the Auto Update and Manifest
pruning rules.
_Avoid_: Rolling deployment, Auto version

**Manifest ID**:
Resolved numeric identifier of the Steam depot manifest selected by a Version spec.
_Avoid_: Version, Build ID

**Manifest**:
Steam's file list for a depot at a given release, identified by a Manifest ID.
_Avoid_: Manifest file

**Manifest file**:
`.manifest` artifact consumed for auth-free downloads alongside `depot.keys`.
_Avoid_: Manifest

**Active Manifest**:
Manifest ID currently backing the Game tree and the running server.
_Avoid_: Current version, Running manifest

**Previous Active Manifest**:
The rollback target retained for latest-tracking deployments: the most recent Manifest Active before
the current one, or the fallback install selected by the pruning rules.
_Avoid_: Old version, Prior install

**Activation record**:
Persisted record of the current Active Manifest and the Manifest that was Active before it.
_Avoid_: Version history, Install log

**Complete Manifest install**:
Numeric Manifest install directory carrying the `.installed` marker.
_Avoid_: Finished install, Valid version

**Incomplete Manifest install**:
Numeric Manifest install directory without the `.installed` marker, reserved for resume.
_Avoid_: Partial download, Broken install

**Manifest pruning**:
Automatic deletion of complete Manifest installs after the Active Manifest install and Game tree
are prepared, keeping only the Active Manifest and Previous Active Manifest installs for
latest-tracking deployments.
_Avoid_: Install cleanup, Cache eviction

**Manifest reclamation**:
Synchronous deletion of complete Manifest installs before a Download when the Install disk-space
check would otherwise fail, keeping the reclamation keep set for latest-tracking deployments.
_Avoid_: Disk cleanup, Space reclaim

**Reclamation keep set**:
The installs preserved during a Download: the requested Manifest install, the recorded Active
Manifest install, every Manifest install backing the current Game tree when present, and the recorded
Previous Active Manifest install when complete, or the fallback install when no complete recorded
previous exists.
_Avoid_: Protected set, Retention set

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
Event causing a Backup: scheduler tick, update restart, SIGTERM shutdown, unexpected crash, or manual invocation. Orthogonal to Category.
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
Path holding Manifest installs, their control files, and the `.prune` staging directory:
`/data/manifests`.
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

**Presence gate**:
The shared rule that applies Player presence evidence to Auto Pause, a save wait, and an Auto Update
restart, with operation-specific waivers.
_Avoid_: Admission, veto list

**Empty-server gate**:
The Presence gate check for an Auto Update download or restart. It excludes A2S evidence and waives
Session freshness, completeness, and malformation while paused, but keeps remote machine entries as a
veto.
_Avoid_: Update veto, session gate

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

**Auto update**:
Automatic check for a newer Manifest and a supervised restart into it when the empty-server gate is
clear.
_Avoid_: Auto-updater, Update daemon

**Pending update**:
A newer Manifest detected but not yet applied because presence, download, or log-only mode prevents
it.
_Avoid_: Queued update, Update queue

**Update check**:
One scheduled Manifest listing performed by Auto Update.
_Avoid_: Poll, Scan
