# Enshrouded Dedicated Server Container

[![CodeQL](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/audit-codeql.yml/badge.svg)](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/audit-codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lincolnthalles/enshrouded-container/badge)](https://scorecard.dev/viewer/?uri=github.com/lincolnthalles/enshrouded-container)
[![build](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/build.yml/badge.svg)](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/build.yml)

Fedora 44 + Wine 11 Docker container for the Enshrouded Dedicated Server with version pinning, mod injection, and automated backups.

## Quick Start

```bash
# Copy and customize the environment
cp .env.example .env

# Start the server
docker compose up -d

# View logs
docker compose logs -f

# Stop the server (creates a final backup)
docker compose down
```

## Features

- **Version pinning**: Pin exact game server versions via Steam manifest IDs. Set `VERSION=latest` for automatic updates or `VERSION=<manifest_id>` for deterministic deployments.
- **Mod injection**: Mount mods at `/data/mods`. A symlink tree layers mods over the game server install, keeping the original files untouched.
- **Config via env vars**: Any `ENSHROUDED_*` env var is converted to a nested JSON key in `enshrouded_server.json`. Works with any config field, including future game updates.
- **Automated backups**: Configurable cron-driven backups (default every 60 min) + shutdown-triggered backup. Backups run at low CPU and I/O priority if cap `SYS_NICE` is available.
- **ntsync**: Can improve game server performance by better emulating Windows synchronization primitives. Requires a host with kernel 6.14+ and mounting `/dev/ntsync` into the container.
- **Resource polling**: Periodically logs CPU% and RSS for the orchestrator and game server process tree. Set `RESOURCE_POLL_INTERVAL` (default 60s) to control the interval.

## Requirements

- Docker 24+

## Environment Variables

### Game version

| Variable        | Default  | Description                                  |
| --------------- | -------- | -------------------------------------------- |
| `VERSION`       | `latest` | Steam manifest ID, `latest`, or `build:<id>` |
| `FORCE_INSTALL` | `false`  | Force re-download even if already installed  |

### Backups

| Variable           | Default         | Description                                        |
| ------------------ | --------------- | -------------------------------------------------- |
| `BACKUP_CRON`      | `*/60 * * * *`  | Cron schedule for backups                          |
| `BACKUP_FORMAT`    | `zstd`          | Compression format: `zstd`, `gzip`, or `zip`       |
| `BACKUP_LEVEL`     | `9`             | Compression level (1-22 for zstd, 1-9 for gzip)    |
| `BACKUP_KEEP_LAST` | `24`            | Number of recent backups to keep (`-1` = keep all) |
| `BACKUP_LIVE`      | `true`          | Enable scheduled backups                           |
| `BACKUP_COLD`      | `true`          | Enable graceful-shutdown backups                   |
| `BACKUP_EMERGENCY` | `true`          | Enable crash-triggered backups                     |
| `BACKUP_DIR`       | `/data/backups` | Backup destination                                 |

### Monitoring

| Variable                 | Default | Description                                    |
| ------------------------ | ------- | ---------------------------------------------- |
| `RESOURCE_POLL_INTERVAL` | `60`    | Seconds between CPU/memory polls (0 = disable) |
| `LOG_TAIL`               | `false` | Tail server log to container stdout            |

### Enshrouded Server config (any `ENSHROUDED_*` prefix)

| Variable                | Default           | Description      |
| ----------------------- | ----------------- | ---------------- |
| `ENSHROUDED_NAME`       | Enshrouded Server | Server name      |
| `ENSHROUDED_SLOT_COUNT` | 16                | Max player slots |
| `ENSHROUDED_QUERY_PORT` | 15637             | Query port       |

> [!WARNING]
> After removing a setting previously applied via environment variable, edit or delete the JSON file manually.
> The env var value will be re-applied on next start only if the key is present in the environment.

See [Environment Variable Config Reference](./docs/env-config-reference.md) for a full list of `ENSHROUDED_*` environment variables.

## Custom Config

Mount a base `enshrouded_server.json` at `/data/config/enshrouded_server.json`. Environment variables override any values in this file. The final config is symlinked into the game server directory.

> [!IMPORTANT]
> The config file can be modified at runtime by the game server (e.g. banned players).

```yaml
volumes:
  - ./enshrouded_server.json:/data/config/enshrouded_server.json
```

Configuration reference:

- [Enshrouded Knowledge Base: Server Gameplay Settings](https://enshrouded.zendesk.com/hc/en-us/articles/20453241249821-Server-Gameplay-Settings)

## Volumes

| Volume / Bind Mount | Container Path     | Purpose                                             |
| ------------------- | ------------------ | --------------------------------------------------- |
| `manifests`         | `/data/manifests`  | Downloaded game versions (versioned by manifest ID) |
| `wineprefix`        | `/data/wineprefix` | Wine prefix directory                               |
| `mods`              | `/data/mods`       | Mod files overlaid via symlinks                     |
| `saves`             | `/data/saves`      | World save data                                     |
| `backups`           | `/data/backups`    | Backup archives                                     |
| `config`            | `/data/config`     | Optional base `enshrouded_server.json`              |
| `logs`              | `/data/logs`       | Server log files                                    |

> **Note**: The symlink tree at `/data/gameserver/` is rebuilt at every container startup. It combines manifest (RO), mods (RO), and a config symlink (RW) — no volume needed for the gameserver directory.

## Mods

Mount your mod directory to `/data/mods`.

The directory structure mirrors the game server at `/data/manifests/<version>/`. Files in `/data/mods/` overlay the manifest files via symlinks in the merged view at `/data/gameserver/`. The `WINEDLLOVERRIDES` environment variable is generated automatically for DLL files.

```text title="/data/mods/"
mods/
  enshrouded_server.kfc   # Replaces/patches the original server file 
  plugins/
    my_plugin.dll          # Custom plugin DLL
```

## Known Manifests

| Manifest ID         | Known working client          | Date        |
| ------------------- | ----------------------------- | ----------- |
| 2174935030716737236 | r1024233, v0.9.1.2 Hotfix 41  | 11 May 2026 |
| 5731192983609912481 | r1018982, v0.9.1.1 Hotfix 40  | 06 May 2026 |
| 954904204024183479  | r1013216, v0.9.1.1 Patch 14   | 29 Apr 2026 |
| 3051703333662412412 | r1004637, v.0.9.1.0 Hotfix 39 | 23 Apr 2026 |
| 5177045887918896292 | r1002673, v.0.9.1.0 Hotfix 38 | 22 Apr 2026 |
| 419436186287499896  | r999467, v0.9.1.0 Hotfix 37   | 21 Apr 2026 |
| 6640441679462295327 | r893400, v0.9.0.4 Hotfix 35   | 26 Jan 2026 |
| 1738270353113680321 | r611358, v0.7.4.0             | 02 Dec 2024 |

Ps: you must cross-reference [client patch notes](https://steamdb.info/app/1203620/patchnotes/) dates with [server manifest](https://steamdb.info/depot/2278521/manifests/) dates to find matching client/server versions.

- [Depot 2278521 for Enshrouded Dedicated Server](https://steamdb.info/depot/2278521/manifests/)
- [Depot 1203621 for Enshrouded Client](https://steamdb.info/depot/1203621/manifests/)

## Ports

| Port  | Protocol | Purpose                                                |
| ----- | -------- | ------------------------------------------------------ |
| 15636 | UDP      | Game server data (Unconfigurable; likely query port-1) |
| 15637 | UDP      | Game server query                                      |
| 27015 | TCP      | SRCDS Rcon port                                        |
| 27015 | UDP      | gameplay traffic                                       |

[Required Ports for Steam](https://support.steampowered.com/kb_article.php?ref=8571-GLVN-8711)

## Using old manifests

Anonymous accounts can only download the latest manifest.

If you do not provide any authentication and request an older manifest, the orchestrator will show the Steam QR code on the terminal for you to authenticate via the mobile app.

> [!NOTE]
> Downloading older manifests is a flaky process as the CDN tends to keep only the latest manifests.
> If you encounter issues (e.g., `ServiceUnavailable`, `NotFound`), insist, try again later or use a different manifest.

### Downloading with Steam authentication

Use `download` for one-time authenticated download:

```bash
# Interactive (DepotDownloader prompts for password)
docker compose run --rm enshrouded download 954904204024183479 --steam-username youruser

# Non-interactive (password via env var — use secrets management in CI)
STEAM_USERNAME=youruser STEAM_PASSWORD=yourpass docker compose run --rm enshrouded download 954904204024183479
```

### Downloading via ManifestHub

ManifestHub is a community service that provides access to older manifests. It is used as a fallback when Steam authentication is not provided.

You must pass-in `MANIFESTHUB_API_URL` and your own `MANIFESTHUB_API_TOKEN` to use this feature.

```bash
docker compose run --rm enshrouded download 954904204024183479 --api-url https://manifest-api-url.gg --api-token yourtoken
```

### Inserting manifests manually

If you already have the game server files, place them directly into `/data/manifests/<manifest_id>/` and create an empty `.installed` marker file. The orchestrator will recognize it as a valid installed version on the next start.

```bash
mkdir -p data/manifests/1234567890
# ... copy game files into the directory ...
touch data/manifests/1234567890/.installed
```

## Tech Stack

- Fedora 44
- Wine 11
- DepotDownloader 3.4.0.2
- Python 3.14+ (enshctl container orchestrator)
