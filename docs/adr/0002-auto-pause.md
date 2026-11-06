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
- **A2S-only wake**: the live client sends an A2S query before joining; filtering it would prevent a
  normal direct-IP join. `any` is the default, with `ignore-a2s` opt-in.
- **A2S player count as truth**: DLL mods can report zero while a player is in-world. A2S is an
  advisory positive-only veto; the log tracker and Session machine table remain authoritative.
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
- `AF_PACKET` needs `CAP_NET_RAW`; the queue fallback sees all traffic and cannot honor
  `ignore-a2s`.
- Shutdown must `SIGCONT` every stopped process before `SIGINT`, including when the wrapper or game
  already exited.
