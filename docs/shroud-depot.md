# Run a Shroud Depot instance

A Shroud Depot server runs a community save as a shared item depot. Players take items, and Auto
Rollback restores the save on a timer so the inventories restock. This guide uses Docker Compose.

Run the commands from the directory that contains your compose file. The paths below use the
`enshrouded-data/` directory created by the sample
[`docker-compose.yml`](../deploy/docker-compose.yml).

## 1. Get a depot save

Search the [Enshrouded Discord](https://discord.com/invite/WynEgUx6ws) for a recent depot save and
download it. Use a save shared for the current game version. Community saves are unofficial, so use
a source you trust. Extract the archive first if the download is compressed.

## 2. Place the save

Rename the save file to `world0.ksd` (v1.0+ naming) and put it in the saves directory:

```bash
mkdir -p enshrouded-data/saves
mv /path/to/depot-save.ksd enshrouded-data/saves/world0.ksd
```

The sample compose mounts `enshrouded-data/saves/` at `/data/saves/` in the container. Start with
an empty saves directory, or move the existing world aside first.

## 3. Create the cold backup

For this first run, leave `ROLLBACK_ENABLED` unset or set it to `false`. Leave `BACKUP_COLD`
enabled (the default). Start the server:

```bash
docker compose up -d
docker compose logs -f enshrouded
```

The server logs `Switching state from LoadEcsScene to Run` when the world is ready. Wait for that
line and for the server to accept connections. The first start downloads about 8 GB of game server
files, so it can take a while. `Ctrl+C` stops the log stream, not the server.

Stop the container:

```bash
docker compose stop enshrouded
```

A graceful stop creates a cold backup. The stop waits for the backup, so it can take up to five
minutes.

List the cold backups:

```bash
ls -1 enshrouded-data/backups/cold/
```

The container path is `/data/backups/cold/`. Copy the newest filename, for example
`enshrouded-20261111-033441-cold.tar.zst`.

## 4. Enable rollback

Add these keys to your `enshrouded.env` file, replacing existing values.

```bash
VERSION=latest
AUTO_UPDATE_ENABLED=true
AUTO_UPDATE_CRON="*/60 * * * *"  

ROLLBACK_ENABLED=true
ROLLBACK_FILE=enshrouded-20261111-033441-cold.tar.zst
ROLLBACK_CRON="*/60 * * * *"

ENSHROUDED_NAME=Shroud Depot **RESETS EVERY HOUR**
ENSHROUDED_USER_GROUPS__0__NAME=Default
ENSHROUDED_USER_GROUPS__0__PASSWORD=
ENSHROUDED_USER_GROUPS__0__CAN_KICK_BAN=false
ENSHROUDED_USER_GROUPS__0__CAN_ACCESS_INVENTORIES=true
ENSHROUDED_USER_GROUPS__0__CAN_EDIT_WORLD=false
ENSHROUDED_USER_GROUPS__0__CAN_EDIT_BASE=false
ENSHROUDED_USER_GROUPS__0__CAN_EXTEND_BASE=false

ENSHROUDED_ENABLE_VOICE_CHAT=false
ENSHROUDED_ENABLE_TEXT_CHAT=true
```

> Alternatively, add the environment variables directly to your `docker-compose.yml`
> file in the `environment:` block under the `enshrouded` service.

- `ROLLBACK_FILE` takes the exact filename, not a path. The container searches every backup category
  for it.

- `ROLLBACK_CRON` sets how often the depot restocks. Use `*/30 * * * *` for every 30 minutes, or
  `*/60 * * * *` for every 60 minutes. Pick the interval based on how many players use the depot.

Keep `VERSION` at `latest` and `AUTO_UPDATE_ENABLED` at `true` so the server follows game updates.
With rollback enabled, an update restart restores the pinned backup before the server launches
again.

While rollback is active, the container does not create automatic live, cold, or emergency
backups. A manual `enshctl backup` still works.

## 5. Start the depot

```bash
docker compose up -d
docker compose logs -f enshrouded
```

The logs show the restore before launch:

```text
Auto rollback: restoring enshrouded-20261111-033441-cold.tar.zst…
Auto rollback: restore complete
```

Each cron tick stops the server, restores the save, and launches it again. The restart disconnects
players.

## Resources

- [Shroud Depot blueprint and item locator](https://enshrouded.gamevault.in/shroud-depot)
- [Reddit search for depot-related posts](https://www.reddit.com/r/Enshrouded/search/?q=depot&kwfEligible=1)
- [Enshrouded Discord](https://discord.com/invite/WynEgUx6ws)

For rollback details, see the [Backup system](backup.md).
