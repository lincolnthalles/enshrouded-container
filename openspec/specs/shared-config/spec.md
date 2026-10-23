## Purpose

Centralized configuration for the enshctl orchestrator: settings seam, ownership identity, and default filesystem locations.

## Requirements

### Requirement: Default filesystem locations

Default persistent locations SHALL live under `/data/`: `/data/saves`, `/data/logs`, `/data/manifests`, `/data/config`, `/data/backups`, `/data/mods`, and `/data/wineprefix`. The Game tree at `/data/gameserver/` is container-internal (rebuilt every start, see `game-tree-rebuild`). User-configured destinations (`BACKUP_DIR`, absolute save/log directories) MAY point outside `/data/`. No module SHALL define its own ad-hoc persistent location.

#### Scenario: Defaults under /data

- **WHEN** no overrides are configured
- **THEN** saves SHALL default to `/data/saves`, logs to `/data/logs`, and backups to `/data/backups/`

#### Scenario: User override outside /data

- **WHEN** `BACKUP_DIR` points outside `/data/`
- **THEN** Backups SHALL be stored there (see `backup-system`)

### Requirement: Typed settings seam

All environment-derived configuration SHALL flow through a single frozen settings object, loaded once per process entrypoint and passed to subsystems via parameters. Subsystems SHALL NOT read process environment directly for configured values; the settings loader, the `ENSHROUDED_*` config merge (see `config-management`), child-process environment forwarding, and the removed-setting check are the only direct environment reads.

#### Scenario: Settings loaded once at startup

- **WHEN** the `start` command runs
- **THEN** settings SHALL be loaded once per process entrypoint and the resulting object SHALL be passed to subsystems; the backup child process SHALL reload settings from its inherited environment

#### Scenario: Settings are frozen

- **WHEN** a settings object is created
- **THEN** attempting to modify an attribute SHALL fail

#### Scenario: Testable without env var manipulation

- **WHEN** a test needs custom settings
- **THEN** it SHALL construct a settings object directly with test values, without modifying process environment

### Requirement: Settings cross the backup subprocess seam

Across the backup subprocess seam, the child SHALL observe the same `BACKUP_*`, `PUID`, and `PGID` values the parent configured. The parent SHALL forward those settings-bearing environment keys (plus the base allowlist) so the child reloads identical backup settings from its inherited environment rather than receiving them over IPC. Keys the backup path never consumes (`MANIFESTHUB_*`, `STEAM_*`, `LOG_TAIL`, `WINE*`, `PERSIST_FILES`) are not forwarded.

#### Scenario: Reload across the backup subprocess seam

- **WHEN** `start` spawns a backup child process
- **THEN** the child SHALL observe the same `BACKUP_*`, `PUID`, and `PGID` values the parent configured

### Requirement: PUID/PGID identity

The system SHALL read `PUID` and `PGID` once at load time (defaults 1000/1000) and expose them as the single ownership identity. All file ownership SHALL use these values; no module SHALL read the variables independently. The server process account itself is owned by `fedora-wine-base`.

#### Scenario: Consistent UID/GID across modules

- **WHEN** `PUID=1001` is set
- **THEN** all modules SHALL resolve uid 1001 from the settings object, not from independent environment reads
