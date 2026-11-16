# Restart the server in-process on a bounded schedule

The container stays up across game server crashes, but multi-day worlds accumulate in-game glitches
such as bugged water physics and environment interactions. Auto Restart resets the world on a
schedule without changing the Active Manifest or requiring the container to exit.

The schedule is one `AUTO_RESTART_CRON` value. It accepts a standard numeric five-field cron
expression for a fixed wall-clock time, or `@every <amount><unit>` for an interval measured from
each server launch. `@every` exists because standard cron cannot express "24 hours after launch":
a daily cron expression is a wall-clock time, while an elapsed interval resets on every relaunch.
One setting keeps the operator surface small and preserves the familiar cron form for fixed times.

A due restart waits for player activity, not for the full empty-server gate. Active handles, a
pending join, and a recognized remote-machine row delay it; A2S, world readiness, stdout health,
tracker degradation, and Session validity do not. The restart exists to clear glitches, so the
evidence most likely to be broken must not block it. `AUTO_RESTART_MAX_DELAY` bounds the wait: the
restart proceeds after the grace window even if players remain. The default is one hour, balancing
player courtesy against a reset that can otherwise be starved indefinitely.

The relaunch reuses the prepared Game tree and Generated config, like a recovery restart. A
scheduled reset does not need a new Manifest, and a full staging pass would add time without
changing the world. The exit path runs the existing cold Backup policy when enabled. An accepted
Auto Update restart wins because it carries a new Manifest; Auto Restart is not started while auto
rollback is active, because rollback owns the restore cadence.

## Considered Options

- **Exit the container and rely on Docker**: rejected for the same reason as ADR 0003. The default
  `on-failure:5` policy does not restart after a clean exit, and the next start would repeat the
  install checks instead of a fast in-process relaunch.
- **Host cron or `docker exec` restart**: rejected because it adds a deployment-specific control
  surface outside the container and cannot use the in-process presence evidence or ordered exit.
- **Separate cron and interval variables**: rejected because one schedule value covers both forms
  and avoids an invalid "both set" state.
- **Wait for players indefinitely**: rejected because a busy server would never receive the reset
  that the feature exists to provide.
- **Restart immediately at the due time**: rejected because it disconnects players without the
  bounded courtesy window.
- **Full staging on every restart**: rejected because the Active Manifest is unchanged and the
  prepared Game tree is already valid.
- **A minimum-uptime guard**: rejected so a trigger shortly after an update or recovery relaunch is
  still honored; cron semantics stay predictable.
- **A live Backup instead of a cold Backup**: rejected because the server stops anyway and a live
  snapshot can race an autosave.

## Consequences

- A daily or elapsed reset clears long-running world glitches without a new game download.
- Players can be disconnected when the grace window expires; the log warns at the due time and at
  expiry.
- A scheduled restart resets `@every` on every relaunch, including update and recovery relaunches.
- A cron trigger missed while the server is stopped is not caught up.
- `AUTO_RESTART_CRON` carries the `@every` extension even though the name follows the existing
  `*_CRON` settings.
- The cold Backup adds the configured lock wait and compression time to the restart.
