## Purpose

Mod file overlay onto the pristine game install via the mods volume.

## Requirements

### Requirement: Mod volume mount

The container SHALL accept mod files via a volume at `/data/mods`. The mod volume SHALL be empty by default. Users SHALL place mod files (replacement or additional game assets) into this directory. Mod DLL files SHALL be detected and used to generate Wine DLL overrides at startup.

#### Scenario: No mods mounted

- **WHEN** `/data/mods` is empty or contains no files
- **THEN** the game SHALL run with the pristine (unmodified) game install and the default `WINEDLLOVERRIDES` of `mscoree,mshtml=`

#### Scenario: Mods mounted with replacement files

- **WHEN** `/data/mods/enshrouded_server.json` exists
- **THEN** the modded config SHALL be visible to the game process at the expected path, while the original file remains unchanged on the lower filesystem

#### Scenario: Mods mounted with DLL files

- **WHEN** `/data/mods` contains `.dll` files
- **THEN** the mod DLLs SHALL be visible at the game path AND the corresponding Wine DLL overrides SHALL be generated and applied to the server process

### Requirement: Symlink-tree layering

At container startup, the entrypoint SHALL construct `/data/gameserver/` as a symlink tree via `build_game_tree`: wipe the target directory, create per-file symlinks to the pristine manifest, then overlay mod symlinks on top (unlinking existing destinations first). The config file SHALL be a symlink to `/data/config/enshrouded_server.json`. The symlink tree SHALL be rebuilt from scratch on every start. There is no shutdown-time tree cleanup; the next start wipes and rebuilds the directory.

#### Scenario: Symlink tree constructed on startup

- **WHEN** the container starts
- **THEN** `/data/gameserver/` SHALL be wiped and rebuilt with per-file symlinks from `/data/manifests/<manifest_id>/`
- **AND** mod files from `/data/mods/` SHALL be symlinked on top (existing destinations unlinked first)
- **AND** `/data/gameserver/enshrouded_server.json` SHALL be a symlink to `/data/config/enshrouded_server.json`

#### Scenario: Overlay is cleaned before mount

- **WHEN** `build_game_tree` is called
- **THEN** all contents of `/data/gameserver/` SHALL be removed before the symlink tree is created

#### Scenario: Original files remain accessible

- **WHEN** a mod replaces a file and the mod is removed
- **THEN** the original file from the manifest SHALL be visible again after the next startup (the tree is rebuilt from scratch)

#### Scenario: Runtime writes to config persist

- **WHEN** the game process writes to `enshrouded_server.json` at runtime
- **THEN** the write SHALL go to `/data/config/enshrouded_server.json` through the symlink
- **AND** the write SHALL persist across container restarts

#### Scenario: Runtime writes to non-config files fail safely

- **WHEN** the game process attempts to write to a symlinked manifest file
- **THEN** the write SHALL fail with a permission error (manifest is read-only)

#### Scenario: No shutdown-time tree cleanup

- **WHEN** the container receives SIGTERM
- **THEN** no game-tree cleanup SHALL run; directory cleanup is implicit in the wipe at the next startup

### Requirement: Mod directory structure

The mod volume SHALL mirror the game server directory structure. Files in `/data/mods/` SHALL overlay files at the same relative path in the game install.

#### Scenario: Mod file overrides game file

- **WHEN** a file exists at `/data/mods/subdir/file.dat` and the game install has `subdir/file.dat`
- **THEN** the game process SHALL see the mod version at `/data/gameserver/subdir/file.dat`

#### Scenario: Mod file adds new file

- **WHEN** a file exists at `/data/mods/new_file.dat` and the game install does not have `new_file.dat`
- **THEN** the game process SHALL see the file at `/data/gameserver/new_file.dat`
