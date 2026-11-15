# Suspend the whole Wine tree and wake on query-port traffic

Auto Pause must remove idle CPU use without a forced save or a game command surface. We use
whole-tree `SIGSTOP`, an observed autosave quiescence window, and wake on inbound UDP to the query
port. This keeps the save path honest and matches the client's pre-join traffic, at the cost of
resident memory and a Steam reconnect after resume.

## Considered Options

- **Game-only `SIGSTOP`**: leaves Wine services active; rejected after `winedevice.exe` kept using
  CPU while the game was stopped.
- **Forced save or RCON**: Enshrouded exposes neither. The save gate waits for a completed autosave
  and verifies size and mtime quiescence.
- **A2S-only wake**: the live client sends an A2S query before joining, but other query-port traffic
  can arrive first, so any UDP to the query port wakes the server.
- **Ignore-A2S filtering**: suppressing A2S queries hides the paused server from the client browser,
  so the client cannot discover or wake it. Rejected because it does not work.
- **A2S-only deny list**: Docker-internal probes and other query-port traffic can be classified as
  generic UDP, so the deny list filters every wake packet instead of only A2S queries.
- **Queue-fallback filtering**: queue polling cannot see source addresses. When a deny list is
  configured, including a list with no valid entry, a pause is refused rather than silently
  bypassing the filter.
- **A2S player count as truth**: DLL mods can report zero while a player is in-world. A2S is an
  advisory positive-only veto; the log tracker and Session machine table remain authoritative.
- **Restart on one 4003**: a single session failure can be a wrong group password or a transient
  client error. The guard waits for two failures within 60 seconds and disarms on a completed join.
- **Backup before recovery restart**: a wake failure is not a crash, and a cold backup would delay
  the player. The recovery restart stops cleanly and relaunches without a backup.
- **Container sleep or hibernate**: does not preserve the running Wine state and does not match the
  process-level control we need.

## Consequences

- A paused server consumes no Wine CPU but still holds its resident memory (~694 MB in the probe).
- A paused server may disappear from the Steam browser; direct-IP join is the supported wake path.
- Resume has a Steam reconnect cost of about 10 seconds.
- A force-kill while paused can lose up to one autosave interval; rotating saves mitigate this.
- Scheduled live backups, resource polling, and periodic roster summaries pause with the tree. A
  pause attempt is refused while non-essential background work runs, so the tree is not suspended
  mid-work.
- `AF_PACKET` needs `CAP_NET_RAW`; otherwise the queue fallback observes all traffic to the query
  port. A configured wake deny list requires `AF_PACKET`, so without it Auto Pause keeps the server
  running instead of pausing without the filter.
- Denied wake packets are ignored for the pause decision but are not dropped from the kernel queue.
- A wake or operator resume may leave the server rejecting joins with error 4003. Two failures
  within 60 seconds request one in-process recovery restart for that resume, with no backup and no
  new status field.
- Shutdown must `SIGCONT` every stopped process before `SIGINT`, including when the wrapper or game
  already exited.
