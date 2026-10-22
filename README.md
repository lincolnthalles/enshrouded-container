# Enshrouded Dedicated Server Container

[![CodeQL](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/audit-codeql.yml/badge.svg)](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/audit-codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lincolnthalles/enshrouded-container/badge)](https://scorecard.dev/viewer/?uri=github.com/lincolnthalles/enshrouded-container)
[![CI](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/ci.yml/badge.svg)](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/ci.yml)
[![Build](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/build.yml/badge.svg)](https://github.com/lincolnthalles/enshrouded-container/actions/workflows/build.yml)

Docker container for the Enshrouded Dedicated Server with version pinning, mod injection, automated backups and ntsync support.

> [!TIP]
> The container is working just fine with game version 1.0.
>
> Images are published on [ghcr.io](https://github.com/lincolnthalles/enshrouded-container/pkgs/container/enshrouded-container).

## Requirements

- Docker 24+ on a Linux host.
- UDP port `15637` reachable by clients.
- Optional: Linux kernel 6.14+ with `/dev/ntsync` available, and `SYS_NICE` cap for low-priority backups.

## Quick Start

Pick one _option_. Click on the options below to expand the instructions.

<details>
<summary><strong>Option A</strong>: docker run (quick trial)</summary>

```bash
mkdir -p enshrouded-data/{backups,config,logs,mods,saves}

docker run -d \
    --name enshrouded \
    --restart on-failure:5 \
    --stop-timeout 300 \
    -p 15637:15637/udp \
    -e TZ=UTC \
    -e ENSHROUDED_NAME="Enshrouded Server" \
    -e ENSHROUDED_SLOT_COUNT=16 \
    -v "$PWD/enshrouded-data/saves:/data/saves" \
    -v "$PWD/enshrouded-data/backups:/data/backups" \
    -v "$PWD/enshrouded-data/config:/data/config" \
    -v "$PWD/enshrouded-data/logs:/data/logs" \
    -v "$PWD/enshrouded-data/mods:/data/mods" \
    -v "$PWD/enshrouded-data/manifests:/data/manifests \
    -v enshrouded_wineprefix:/data/wineprefix \
    ghcr.io/lincolnthalles/enshrouded-container:latest

# Follow logs, then stop (Ctrl+C).
docker logs -f enshrouded
```

</details>

<details>
<summary><strong>Option B</strong>: Compose (recommended for production)</summary>

Download the compose file and the example env file, or clone the repo:

```bash
curl -O https://raw.githubusercontent.com/lincolnthalles/enshrouded-container/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/lincolnthalles/enshrouded-container/main/.env.example
cp .env.example .env

# Start the server
docker compose up -d

# View logs
docker compose logs -f

# Stop the server
docker compose down
```

- [docker-compose.yml](https://github.com/lincolnthalles/enshrouded-container/blob/main/docker-compose.yml)
- [.env.example](https://github.com/lincolnthalles/enshrouded-container/blob/main/.env.example)

</details>

### Quick Start Notes

> [!WARNING]
> The default server has an open `Default` user group with _no password_.
>
> Set `ENSHROUDED_USER_GROUPS__0__PASSWORD` to protect it:
> `docker run -e ENSHROUDED_USER_GROUPS__0__PASSWORD=...`

- The first start downloads the game server files (~8 GB) before launching. Check progress with `docker compose logs -f`. Later starts reuse the downloaded version and only check for updates.

- Automated backups are enabled by default: scheduled hourly plus one on every graceful stop, stored in `./enshrouded-data/backups/` (categories and retention below).

Join the server by clicking Play->Join->Press T (Search by IPv4/domain) and insert your server `IP address:15637` or domain name. When prompted, enter the password of the group you belong to — set via `ENSHROUDED_USER_GROUPS__*` in `.env`.

## Container Features

- **Version pinning**: Pin exact game server versions via Steam manifest IDs. Set `VERSION=latest` (or omit it entirely) for automatic updates on restarts or `VERSION=<manifest_id>` for deterministic deployments.
- **Mod injection**: Mount mods at `/data/mods`. A symlink tree layers mods over the game server install, keeping the original files untouched.
- **Config via env vars**: Any `ENSHROUDED_*` env var is converted to a nested JSON key in `enshrouded_server.json`. Works with any config field, including future game updates.
- **Automated backups**: Configurable cron-driven backups (default every 60 min) + shutdown-triggered backup. Backups run at low CPU and I/O priority if cap `SYS_NICE` is available.
- **ntsync**: Can improve game server performance by accurately emulating Windows synchronization primitives. Requires a host with kernel 6.14+, the ntsync module loaded, and mounting `/dev/ntsync` into the container.
- **Resource polling**: Periodically logs CPU% and RSS for the orchestrator and game server process tree. Set `RESOURCE_POLL_INTERVAL` (default 60s) to control the interval.

## Environment Variables

### Game version

| Variable        | Default  | Description                                  |
| --------------- | -------- | -------------------------------------------- |
| `VERSION`       | `latest` | Steam manifest ID, `latest`, or `build:<id>` |
| `FORCE_INSTALL` | `false`  | Force re-download even if already installed  |

### Backups

<details>
    <summary>Click to expand</summary>

| Variable           | Default         | Description                                                               |
| ------------------ | --------------- | ------------------------------------------------------------------------- |
| `BACKUP_CRON`      | `*/60 * * * *`  | Cron schedule for backups                                                 |
| `BACKUP_FORMAT`    | `zstd`          | Compression format: `zstd`, `gzip`, or `zip`                              |
| `BACKUP_LEVEL`     | format default  | Compression level (1-22 zstd, 1-9 gzip/zip; defaults: zstd 9, gzip/zip 6) |
| `BACKUP_KEEP_LAST` | `24`            | Number of recent backups to keep (`-1` = keep all)                        |
| `BACKUP_LIVE`      | `true`          | Enable scheduled backups                                                  |
| `BACKUP_COLD`      | `true`          | Enable graceful-shutdown backups                                          |
| `BACKUP_EMERGENCY` | `true`          | Enable crash-triggered backups                                            |
| `BACKUP_DIR`       | `/data/backups` | Backup destination                                                        |

</details>

### Monitoring

| Variable                 | Default | Description                                    |
| ------------------------ | ------- | ---------------------------------------------- |
| `RESOURCE_POLL_INTERVAL` | `60`    | Seconds between CPU/memory polls (0 = disable) |
| `LOG_TAIL`               | `false` | Tail server log to container stdout            |

### Enshrouded Server config (any `ENSHROUDED_*` prefix)

See [Environment Variable Config Reference](./docs/env-config-reference.md) for a full list of `ENSHROUDED_*` environment variables.

| Variable                | Default           | Description      |
| ----------------------- | ----------------- | ---------------- |
| `ENSHROUDED_NAME`       | Enshrouded Server | Server name      |
| `ENSHROUDED_SLOT_COUNT` | 16                | Max player slots |
| `ENSHROUDED_QUERY_PORT` | 15637             | Query port       |

> [!WARNING]
> After removing an `ENSHROUDED_*` environment variable, edit or delete the file `/data/config/enshrouded_server.json` manually to remove the setting, or the server will continue to use the old value.

## Custom Config File

<details>
<summary>Click to expand</summary>

> [!TIP]
> The recommended way to configure the server is to use only the environment variables.

You can mount a base `enshrouded_server.json` at `/data/config/enshrouded_server.json`. Environment variables override any values in this file. The final config is symlinked into the game server directory.

```yaml
volumes:
  - ./enshrouded_server.json:/data/config/enshrouded_server.json
```

> [!IMPORTANT]
> The config file can be modified at runtime by the game server (e.g. banned players).
> Do not assume the file will remain unchanged.

Configuration reference:

- [Enshrouded Knowledge Base: Server Gameplay Settings](https://enshrouded.zendesk.com/hc/en-us/articles/20453241249821-Server-Gameplay-Settings)

</details>

## Container Volumes

| Host path (compose default)    | Container Path     | Purpose                                             |
| ------------------------------ | ------------------ | --------------------------------------------------- |
| `./enshrouded-data/saves`      | `/data/saves`      | World save data                                     |
| `./enshrouded-data/backups`    | `/data/backups`    | Backup archives                                     |
| `./enshrouded-data/config`     | `/data/config`     | Optional base `enshrouded_server.json`              |
| `./enshrouded-data/logs`       | `/data/logs`       | Server log files                                    |
| `./enshrouded-data/mods`       | `/data/mods`       | Mod files overlaid via symlinks                     |
| `./enshrouded-data/manifests`  | `/data/manifests`  | Downloaded game versions (versioned by manifest ID) |
| `enshrouded_wineprefix` volume | `/data/wineprefix` | Wine prefix directory                               |

> The internal symlink tree at `/data/gameserver/` is rebuilt at every container startup. It combines manifest (RO), mods (RO), and a config symlink (RW). No volume needed for it.

## Mods

Mount your mods directory to `/data/mods`.

```text
mods/                       # mounted to /data/mods
  ├── dbghelp.dll
  ├── enshrouded_server.kfc # Overrides the original server file 
  └── mods/
      └── my_plugin.dll     # Custom plugin DLL
```

Remove mods by cleaning the `mods` directory and restarting the container.

> Mods are overlaid at runtime on top of the active game server manifest, meaning you can safely override server binaries or add plugins.
>
> The required `WINEDLLOVERRIDES` environment variable is handled automatically for DLL files.

## Network Ports

| Port  | Protocol | Purpose                                               |
| ----- | -------- | ----------------------------------------------------- |
| 15637 | UDP      | Game server traffic (published in compose by default) |

[Required Ports for Steam](https://support.steampowered.com/kb_article.php?ref=8571-GLVN-8711)

## Using previous manifests

Steam Depot _Manifests_ describe a specific snapshot or version of a game's content.

> [!IMPORTANT]
> Avoid rollbacks.
> Database changes may occur between versions, and major rollbacks may break your world save.

Anonymous accounts can only download the latest manifest.

If you do not provide any authentication and request an older manifest, the orchestrator will show the Steam QR code on the terminal for you to authenticate via the mobile app. Follow the startup process with `docker logs enshrouded -f`.

> [!NOTE]
> Downloading older manifests is a flaky process as the CDN tends to keep only the latest manifests.
> If you encounter issues (e.g., `ServiceUnavailable`, `NotFound`), insist, try again later or use a different manifest.

### Existing files

> [!TIP]
> Old manifests are kept by the orchestrator as long as there’s enough free storage, allowing you to pin `VERSION` to any manifest that is still available in storage.
>
> This fits most users who want to upgrade at a slower pace due to mod compatibility or other reasons.

### Alternative methods

<details>
<summary>Inserting manifests manually</summary>

If you already have the game server files, place them directly into `/data/manifests/<manifest_id>/` and create an empty `.installed` marker file. The orchestrator will recognize it as a valid installed version on the next start.

```bash
mkdir -p data/manifests/1234567890
# ... copy game files into the directory ...
touch data/manifests/1234567890/.installed
```

</details>

<details>
<summary>Downloading with Steam authentication</summary>

Use the `download` command for one-time authenticated download:

```bash
# Interactive (DepotDownloader prompts for password)
docker compose run --rm enshrouded download 2174935030716737236 --steam-username youruser

# Non-interactive (password via env var — use secrets management in CI)
STEAM_USERNAME=youruser STEAM_PASSWORD=yourpass docker compose run --rm enshrouded download 954904204024183479
```

</details>

<details>
<summary>Downloading via ManifestHub</summary>

ManifestHub is a community service that provides access to older manifests. It is used as a fallback when Steam authentication is not provided.

You must source and pass-in `MANIFESTHUB_API_URL` plus your own `MANIFESTHUB_API_TOKEN` to use this feature.

```bash
docker compose run --rm enshrouded download 2174935030716737236 --api-url https://manifest-api-url.gg --api-token yourtoken
```

</details>

### Known server Manifests

<details>
<summary>Click to expand</summary>

| Manifest ID         | Known working client          | Date        |
| ------------------- | ----------------------------- | ----------- |
| 6823302667609042502 | r1269579, v1.0.0.2            | 16 Oct 2026 |
| 2174935030716737236 | r1024233, v0.9.1.2 Hotfix 41  | 11 May 2026 |
| 5731192983609912481 | r1018982, v0.9.1.1 Hotfix 40  | 06 May 2026 |
| 954904204024183479  | r1013216, v0.9.1.1 Patch 14   | 29 Apr 2026 |
| 3051703333662412412 | r1004637, v.0.9.1.0 Hotfix 39 | 23 Apr 2026 |
| 5177045887918896292 | r1002673, v.0.9.1.0 Hotfix 38 | 22 Apr 2026 |
| 419436186287499896  | r999467, v0.9.1.0 Hotfix 37   | 21 Apr 2026 |
| 6640441679462295327 | r893400, v0.9.0.4 Hotfix 35   | 26 Jan 2026 |
| 1738270353113680321 | r611358, v0.7.4.0             | 02 Dec 2024 |

Note: you must cross-reference _client patch note dates_ with _server manifest dates_ to find matching client/server versions.

- [Client patch notes](https://steamdb.info/app/1203620/patchnotes/)
- [Enshrouded Client Manifests](https://steamdb.info/depot/1203621/manifests/) (Depot 1203621)
- [Enshrouded Dedicated Server Manifests](https://steamdb.info/depot/2278521/manifests/) (Depot 2278521)

</details>

## Tech Stack

- Fedora 44
- Wine 11
- DepotDownloader 3.4.0.2
- Python 3.14+ (enshctl container orchestrator)
