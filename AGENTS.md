# AGENTS.md

Canonical instructions for AI assistants working on this codebase.

## Overview

enshctl — Docker container and CLI for managing an Enshrouded dedicated game server with version pinning, mod injection, and automated backups.

## Rules

- Do NOT circumvent linters or type checkers. If a scoped ignore is best, add it in `pyproject.toml` with a comment explaining why.
- Do not use `__future__` — Python 3.14+.
- When inspecting runtime command calls, run them inside the container to verify before editing code.
- Never create GitHub issues or pull requests. This project only accepts manual human-curated interactions.

### Task completion

Only deliver work after `just gate` succeeds.

### Additional sources

- `openspec/specs/**` — Spec-driven development artifacts (use openspec skills when present).

## Commands

```bash
just gate         # test → lint → typecheck, concise output
just validate     # test → lint → typecheck in sequence
just fmt          # dprint fmt (Python via ruff format)
```

Run bare `just` for the full recipe list.

Venv auto-creates on first run (`uv`). `uv sync` uses `--no-install-project` — the project is never pip-installed in dev; pytest resolves imports via `pythonpath = ["src"]`.

## Testing

pytest with `pythonpath = ["src"]` — imports use full package path: `from enshctl.config import ...`. Tests in `src/tests`. No conftest, no fixtures. Tests manually set/clean env vars with try/finally. Uses `unittest.mock.patch` for isolation.

Private functions are imported and tested directly (the `PLC0415` ignore in test files allows local imports for env isolation).

## Type checking

pyrefly `preset = "strict"`. All new code must have full type annotations.

## Linting

Ruff `select = ["ALL"]` with targeted ignores — see `pyproject.toml`. Per-file ignores exist for test files, `commands/*.py`, and `backup_runner.py`.

## Formatting

dprint (`.dprint.jsonc`). Run with `just fmt` or `dprint fmt`. Python files formatted by `ruff format` via dprint's exec plugin.

## uv caveats

`[tool.uv] exclude-newer = "7 days"` is set. When syncing old branches or pinned deps predating that window, override with `UV_EXCLUDE_NEWER=0` or adjust the cutoff.

## Docker

3-stage build: Python wheel → DepotDownloader (dotnet) → Fedora 44 runtime. `vendor/DepotDownloader/` is built from source in stage 2. Entrypoint: `enshctl`, default command: `start`.

## Gotchas

- **Backup subprocess isolation**: Backups run as child processes of `enshctl backup`, never in-process. Signals to the main process don't cancel backups. `fcntl.flock` prevents concurrent backups. Exit code 1 = lock held (expected), 2 = error.
- **Symlink tree rebuild**: The game tree at `/data/gameserver/` is rebuilt from scratch on every start using `cp -as`. No FUSE or `SYS_ADMIN` required.
- **DepotDownloader quirks**: See `docs/depotdownloader-quirks.md`. The `-manifestfile`/`-depotkeys` flags require the DepotDownloaderMod fork.
- **Free space guards**: `INSTALL_MIN_FREE_SPACE` (10 GiB) blocks install. `BACKUP_MIN_FREE_SPACE_WARN` (2 GiB) and `BACKUP_MIN_FREE_SPACE_STOP` (1 GiB) control backup behavior.
- **PERSIST_FILES**: Comma-separated relative paths persisted to `/data/config/` and symlinked into the game tree. Path traversal entries are skipped.
- **Orchestrator logging**: `ORCHESTRATOR_LOG_FILE` enables file logging. `ORCHESTRATOR_LOG_LEVEL` controls level (default `WARNING`). Game server entries filtered out.
