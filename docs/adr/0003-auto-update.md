# Restart into the newest Manifest from inside the running container

Auto Update must work under the default `on-failure:5` restart policy, which does not restart a
container after a clean exit. We keep the container process alive, stop the game, rebuild the Game
tree from the new Manifest install, and launch a new server process in the same container. The
update is enabled by default for `latest`, checks hourly, downloads eagerly, and restarts only when
the empty-server gate is clear. A cold backup runs before the restart when `BACKUP_COLD` is true.

## Considered Options

- **Exit the container and rely on Docker**: rejected because `on-failure:5` does not restart after
  a successful update, and asking every deployment to change its restart policy is fragile.
- **Re-exec the entrypoint**: rejected because it discards all in-memory lifecycle state and makes
  the restart harder to observe and test than a supervised relaunch loop.
- **Download only when empty**: supported through `AUTO_UPDATE_DOWNLOAD_ONLY_WHEN_EMPTY`, but not the
  default. Downloading while players are online keeps the empty-server window short; the running
  Manifest install is never modified.
- **A2S as a restart veto**: rejected because A2S is advisory and can time out. The log-derived
  roster, pending join, tracker, stream, and Session block are the same evidence Auto Pause trusts.
- **Delete old Manifest installs after an update**: rejected because it removes the rollback target.
  The install disk-space guard blocks and warns when space runs out instead.

## Consequences

- A `latest` server can restart unattended after a game release.
- Mod files only produce a startup warning; Auto Update does not block or adapt to them.
- A player joining between the final presence check and `SIGINT` can be disconnected.
- Old Manifest installs accumulate by design and eventually require operator cleanup.
- Shutdown aborts an in-flight update download; the partial Manifest install resumes next run.
