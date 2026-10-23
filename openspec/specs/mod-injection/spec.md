## Purpose

Mod file supply via the mods volume; layering mechanics live in `game-tree-rebuild`, DLL override generation in `dll-override-generation`.

## Requirements

### Requirement: Mod volume

The container SHALL accept mod files via a volume at `/data/mods`, created when absent and empty by default. The mod volume SHALL mirror the game server directory structure: files at the same relative path shadow Manifest install files in the Game tree (see `game-tree-rebuild`). The server config path is exempt: it SHALL always resolve to the persisted config, never to a mod-supplied file.

#### Scenario: No mods mounted

- **WHEN** the mods volume is empty or contains no files
- **THEN** the game SHALL run with the unmodified Manifest install

#### Scenario: Placed mod file visible in Game tree

- **WHEN** a file is placed in the mods volume at a relative path
- **THEN** the game process SHALL see the file at the same Game tree path (shadowing any Manifest install file per `game-tree-rebuild`)

#### Scenario: Server config exempt from overlay

- **WHEN** a file exists in the mods volume at the server config path
- **THEN** the game process SHALL see the persisted config at that Game tree path, not the mod file
