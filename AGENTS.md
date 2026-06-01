# AGENTS.md

## Rules

- Do NOT run builds directly. If a build is invaluable, instruct the user briefly on how to do it.
- Do NOT default to circumventing linters or type checkers. If you are confident that a lint is best ignored for this project, add a scoped ignore in `pyproject.toml` with a brief comment explaining why.
- WHEN correcting or inspecting runtime command calls, run them inside the container to verify the results before editing code.

### Task Completion Requirements

Only deliver work after checking whether `just quick-validate` succeeds.

### Core Priorities

1. Reliability: safely rollback and cleanup, never leaving the system in an inconsistent state or causing data loss.
2. Predictable behavior under load and during failures.
3. Performance.

If a tradeoff is required, choose correctness and robustness over short-term convenience.

### Maintainability

Long term maintainability is a core priority. When adding new functionality, first check if there is shared logic that can be extracted to a separate module. Duplicate logic across multiple files is a code smell and should be avoided. Don't be afraid to change existing code. Don't take shortcuts by just adding local logic to solve a problem.

### Additional Sources

- `openspec/specs/**` — Spec-driven development artifacts (use openspec skills when present).

## Commands

```bash
just lint       # ruff check src/enshctl src/tests/
just typecheck  # mypy src/enshctl (strict, NOT tests)
just test       # pytest src/tests/ -v
just fmt        # dprint fmt
just quick-validate  # runs test, lint and typecheck, showing a concise agent-oriented output
just validate   # runs test, lint, typecheck in sequence
just build      # uv build (wheel, used by Dockerfile)
just dev        # docker compose -f docker-compose.dev.yml up -d --build --force-recreate && logs -f
just dev-config # docker compose -f docker-compose.dev.yml run --build --rm enshrouded debug-config
just clean      # remove .venv, caches, Docker builder/cache
```

Run order: **lint -> typecheck -> test** after changes. The venv auto-creates on first run (uses `uv`).

## Architecture

Docker container (Fedora 44 + Wine 11) for the Enshrouded dedicated server. Python orchestrates the lifecycle as PID 1:

```text
install -> mod layering (symlink tree) -> config generation -> server start -> scheduled backups -> graceful shutdown
```

### Source layout

- `src/enshctl/` — main package
  - `__main__.py` — thin CLI dispatcher (argparse subcommands)
  - `config.py` — env var -> JSON config generation
  - `backup.py` — zstd/gzip/zip backup, file locking, cron parser, archive verify/decompress
  - `backup_runner.py` — subprocess runner that lowers CPU/IO priority, acquires lock, compresses, prunes
  - `retention.py` — restic-inspired retention engine (hourly/daily/weekly/monthly/yearly buckets)
  - `install.py` — DepotDownloader version resolution and download (multi-depot discovery, ManifestHub API, depot keys from git repos)
  - `mods.py` — symlink tree mod injection, DLL override generation
  - `commands/` — subcommand implementations
    - `start.py` — full server lifecycle (directory setup, Wine prefix init, install, mount, config, backup scheduler, server process, signal handling, log tail)
    - `backup.py` — CLI wrapper around backup_runner
    - `restore.py` — interactive TUI restore (Textual) or file/when-based restore
    - `prune.py` — enforce retention rules with dry-run support
    - `verify.py` — archive integrity checker
    - `install.py` — standalone install subcommand
    - `download.py` — download specific manifest with Steam auth or ManifestHub token
    - `debug_config.py` — dump resolved config
    - `version_info.py` — show installed version info
- `src/tests/` — test files (pytest)
- `config/enshrouded_server.json` — example base config shipped in the image at `/data/config/`

### Entrypoint

`enshctl` console script (defined in `pyproject.toml`). Dockerfile: `ENTRYPOINT ["enshctl"]`, `CMD ["start"]`. The `commands/` package exposes a `COMMANDS` dict that `__main__.py` dispatches into.

### Backup subsystem

Backups run as **separate subprocesses** (`enshctl backup`), not in-process. The `start` command spawns them via `subprocess.Popen` with `start_new_session=True`. This means:

- Backup runs in its own process group, with CPU priority lowered via `os.nice(19)` and IO priority via `ionice -c3`.
- File locking (`fcntl.flock`) prevents concurrent backup operations. Exit code 1 = lock held (expected), 2 = error.
- Backup files are named `enshrouded-YYYYMMDD-HHMMSS[-cold|-emergency].<ext>`.
- Three backup categories: `live` (scheduled), `cold` (graceful shutdown), `emergency`.
- Formats: `zstd` (default, `.tar.zst`), `gzip` (`.tar.gz`), `zip` (`.zip`). Level configurable via `BACKUP_LEVEL`.
- First backup runs immediately on server start, then repeats per cron expression (`BACKUP_CRON`, default `*/60 * * * *`).

### Retention model

Restic-inspired retention via `retention.py`. Controlled by `BACKUP_KEEP_*` env vars:

- `BACKUP_KEEP_LAST` — number of most recent backups to keep (default 24, -1 = keep all, 0 = no limit)
- `BACKUP_KEEP_HOURLY`, `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`, `BACKUP_KEEP_MONTHLY`, `BACKUP_KEEP_YEARLY` — time-bucket counts
- Applied per category (live/cold/emergency independently)
- `prune` subcommand runs standalone; `backup_runner` applies retention after each backup
- Old `BACKUP_RETENTION` env var is ignored (warning logged if set)

### Mod injection

On startup, `build_game_tree()` wipes `/data/gameserver/` and reconstructs it as a symlink tree: manifest files (RO) from `/data/manifests/<version>`, mod files (RO) from `/data/mods`, and a config symlink pointing to `/data/config/enshrouded_server.json`. The game tree is rebuilt from scratch on every start, making it fully ephemeral. Manifest files are marked read-only (`chmod -R a-w`) after download as defense-in-depth.

DLL override generation: scans `/data/mods/**/*.dll` and generates `WINEDLLOVERRIDES`. DLLs with `win*` prefix get `n,b` override; others get `n`. Baseline `mscoree,mshtml=` always prepended.

## Key conventions

- **Config system**: `ENSHROUDED_*` env vars -> nested JSON in `enshrouded_server.json`. Double underscores delimit nesting: `ENSHROUDED_GAME_SETTINGS__ENABLE_DURABILITY=true` -> `{"gameSettings": {"enableDurability": true}}`. Supports array indexing via numeric segments: `ENSHROUDED_USER_GROUPS__0__NAME=Admin`.
- **Version pinning**: `VERSION=latest` resolves via DepotDownloader manifest list. Accepts manifest IDs or `build:<id>`.
- **FORCE_INSTALL**: Set `FORCE_INSTALL=1` to trigger full re-download even if a version is already installed.
- **Steam IDs**: App `2278520`, Depot `2278521`.
- **Log-tail**: `--log-tail` flag (or env `LOG_TAIL=1`) tails the game's log file to stdout during `start`.
- **TZ env var**: Container timezone is set from `TZ` env var (default UTC), symlinked to `/etc/localtime`.
- **Wine prefix**: Initialized lazily on first run via `wineboot --init` (creates `.wineboot` marker). Uses `WINEPREFIX=/data/wineprefix`, runs via `xvfb-run` with minimal X allocation.
- **Signal handling**: SIGTERM triggers graceful shutdown: SIGINT to server process, wait for in-progress backup, cold backup if `BACKUP_COLD=1`, then clean up game tree.
- **PERSIST_FILES**: Comma-separated relative paths of additional files persisted to `/data/config/` and symlinked into the game tree. Default includes `enshrouded_server.json` (always). Path traversal entries are skipped.

## Subcommands

| Command        | Description                                               |
| -------------- | --------------------------------------------------------- |
| `start`        | Full server lifecycle (default)                           |
| `backup`       | Run backup now (with lock, priority lowering, retention)  |
| `restore`      | Restore a backup (interactive TUI, `--file`, or `--when`) |
| `prune`        | Enforce retention rules (`--dry-run` supported)           |
| `verify`       | Check backup archive integrity (`--file` or `--all`)      |
| `install`      | Download/install game files                               |
| `download`     | Download a specific manifest with auth                    |
| `debug-config` | Dump resolved config                                      |
| `version-info` | Show installed version info                               |

## Testing

pytest `pythonpath = ["src"]` — imports use the full package path: `from enshctl.config import ...`. Test paths: `src/tests`. No conftest or fixtures; tests manually set/clean env vars using try/finally blocks. Uses `unittest.mock.patch` for isolation (e.g., patching `get_backup_dir`). Private functions are imported and tested directly (the `PLC0415` ignore in test files allows local imports for env isolation).

## Type checking

mypy strict (`disallow_any_generics`, `disallow_incomplete_defs`, `disallow_untyped_defs`, `strict_equality`, `warn_unused_ignores`, `local_partial_types`). `mypy_path = "src/enshctl"`. New code must have full type annotations.

## Linting

Ruff `select = ["ALL"]` with targeted ignores:

- `D101`, `D102`, `D103` — docstrings not required
- `S603`, `S607`, `S202`, `S108`, `S310` — subprocess/security relaxations for container orchestration
- `PLR0911`, `PLR0912`, `PLR2004` — return statements, branching, magic values
- `TRY003` — long exception messages outside class
- `T201` — print found (used in debug-config)
- `COM812` — missing trailing comma (redundant with formatter)
- `FBT001`, `FBT002` — boolean positional args
- `C901` — complexity
- `PLW0602`, `PLW0603` — global variable usage
- `ANN001` — missing type annotations for some args
- `ARG001` — unused args
- `PERF401` — list comprehension optimization
- `PLC0415` — local imports allowed in `commands/*.py` (lazy CLI dispatch) and `backup.py` (circular import avoidance)

Per-file: test files ignore `S101`, `S105`, `S106`, `PLC0415`, `SLF001`, `PT019`. `backup.py` also ignores `TRY300` (return in try/except is intentional).

## Formatting

dprint is the canonical formatter (`.dprint.jsonc`). Run with `just fmt`. Handles JSON, YAML, TOML, Markdown, Python (via ruff plugin), and justfiles. Zed auto-formats on save.

EditorConfig: spaces, LF. Markdown indent: 4. Justfile indent: 4. Python line length: 120.

## Docker

- Multi-stage build: 3 stages
  1. `quay.io/fedora/python-314-minimal` — builds wheel with `uv build`
  2. `mcr.microsoft.com/dotnet/sdk:9.0` — builds DepotDownloader (self-contained, single-file, trimmed)
  3. `quay.io/fedora/fedora-minimal:44` — runtime (Fedora + Wine + Python wheel)
- `WINESTAGING` build arg: `false` = wine-core (3.54 GB), `true` = winehq-staging (3.88 GB)
- Runtime deps: `python3`, `procps-ng`, `util-linux`, `xorg-x11-server-Xvfb`
- `AGENTS.md` is in `.dockerignore`

## Dev compose

`docker-compose.dev.yml` mounts `./enshrouded-data/*` bind mounts (not named volumes), defines env vars inline (no `.env.dev` file). Uses `SYS_NICE` capability. Optional `ntsync` device passthrough. Runs with `just dev`.

## Gotchas

- **Backup subprocess isolation**: Backups always run as child processes of `enshctl backup`, never in-process. This means signals to the main process don't automatically cancel backups — they wait for completion before shutdown.
- **Symlink tree rebuild**: The game tree is rebuilt from scratch on every start using `cp -as`. No FUSE or SYS_ADMIN required.
- **Cron parsing**: `backup.py` has a `parse_cron()` function that converts cron expressions to seconds intervals. Falls back to 300s if parsing fails.
- **Local imports in commands**: `commands/*.py` uses local imports for `argparse`, `rich`, and `textual` to keep CLI dispatch fast. The `PLC0415` lint rule is scoped for this.
- **Circular import avoidance**: `backup.py` uses local imports in `start_scheduler` to avoid circular imports with `backup_runner`.
- **DepotDownloader quirks**: See `docs/depotdownloader-quirks.md`. The `-manifestfile`/`-depotkeys` flags require the DepotDownloaderMod fork or specific DepotDownloader versions.
- **Lock file**: `.lock` file in backup dir. Uses `fcntl.flock` with `LOCK_NB` for non-blocking attempts. Exit code 1 = lock held, 2 = error.
- **Archive format detection**: Based on file extension (`.tar.zst`, `.tar.gz`, `.zip`). Not content-sniffed.
- **Restore confirmation**: Interactive TUI restore requires Textual. Falls back to `input()` prompt if Textual unavailable.
