# Rebuild game tree as symlinks instead of FUSE union filesystem

The game server needs a Mod overlay layered onto its Manifest install, which funionfs provided at the cost of `SYS_ADMIN` and `/dev/fuse`, blocking Podman rootless, Docker Desktop defaults, and hardened Kubernetes. We rebuild the Game tree from scratch on every start as a symlink tree onto the Manifest install plus Mod overlay, because only one file in the tree is ever written and symlink creation is near-instant with zero kernel capabilities.

## Considered Options

- **funionfs (FUSE union filesystem)**: the previous approach; requires `SYS_ADMIN` and `/dev/fuse` device passthrough.
- **Kernel overlayfs**: still requires `SYS_ADMIN` in most container runtimes.
- **`cp -a` (full copy)**: duplicates the full game install on every start; slow first start, wastes disk.
- **`cp -al` (hardlinks)**: zero disk overhead, but a game write to a shared link risks corrupting the Manifest install.

## Consequences

- The Game tree is ephemeral: wiped and rebuilt on every start, so no hot-swap of mods and no shutdown-time cleanup.
- Any runtime write outside `PERSIST_FILES` fails against the read-only Manifest install instead of being silently absorbed by an overlay; new writable files need a `PERSIST_FILES` entry, not a code change.
- `/data/overlay/` no longer exists; scripts referencing it must be updated.
