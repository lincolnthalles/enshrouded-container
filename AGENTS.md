# AGENTS.md

Canonical instructions for AI assistants working on this codebase.

## Overview

enshctl — Docker container and CLI for managing an Enshrouded dedicated game server with version pinning, mod injection, and automated backups.

## Rules

- Do NOT default to circumventing linters or type checkers. If a lint ignore is best, add a scoped ignore in `pyproject.toml` with a comment explaining why.
- WHEN correcting or inspecting runtime command calls, run them inside the container to verify results before editing code.
- This project uses Python 3.14+. Do not use the `__future__` module.
- Avoid boilerplate tests. Rely on behavioral coverage instead.
- Never create GitHub issues or pull requests. This project only accepts manual human-curated interactions. If asked, inform and stop.

### Engineering Priorities

Correctness > predictability/robustness > maintainability > performance. When in doubt, choose operational safety.

### Task completion

Only deliver work after `just quick-validate` succeeds.

### Additional sources

- `openspec/specs/**` — Spec-driven development artifacts (use openspec skills when present).

## Commands

```bash
just fmt             # dprint fmt (delegates Python to ruff format via exec plugin)
just quick-validate  # test + lint + typecheck, concise output
just validate        # test + lint + typecheck in sequence
```

Run bare `just` for the full recipe list.

Venv auto-creates on first run (`uv`). `uv sync` uses `--no-install-project` — the project is never pip-installed in dev; pytest resolves imports via `pythonpath = ["src"]`. The `validate` recipe runs pytest → ruff check → mypy.

## Testing

pytest with `pythonpath = ["src"]` — imports use full package path: `from enshctl.config import ...`. Tests in `src/tests`. No conftest, no fixtures. Tests manually set/clean env vars with try/finally. Uses `unittest.mock.patch` for isolation.

Private functions are imported and tested directly (the `PLC0415` ignore in test files allows local imports for env isolation).

## Type checking

mypy strict. `mypy_path = "src/enshctl"`. New code must have full type annotations.

Two modules relax `warn_return_any`: `enshctl.config`, `enshctl.install`. One module (`enshctl.commands.restore`) disables `misc` error code. Test files (`test_*.py`) use `ty` (not mypy) with relaxed rules.

## Linting

Ruff `select = ["ALL"]` with targeted ignores — see `pyproject.toml` for the full list. Per-file ignores exist for test files, `commands/*.py`, and `backup_runner.py`.

## Formatting

dprint is the canonical formatter (`.dprint.jsonc`). Run with `just fmt`. Python files formatted by `ruff format` via dprint's exec plugin — `dprint fmt` is the single command for all languages. Python line length: 120.

## uv caveats

`[tool.uv] exclude-newer = "7 days"` is set. When syncing old branches or pinned deps predating that window, override with `UV_EXCLUDE_NEWER=0` or adjust the cutoff.

## Docker

3-stage build: Python wheel → DepotDownloader (dotnet) → Fedora 44 runtime. `vendor/DepotDownloader/` is built from source in stage 2. Entrypoint: `enshctl`, default command: `start`.

## Gotchas

- **Backup subprocess isolation**: Backups run as child processes of `enshctl backup`, never in-process. Signals to the main process don't cancel backups. `fcntl.flock` prevents concurrent backups. Exit code 1 = lock held (expected), 2 = error.
- **Symlink tree rebuild**: The game tree at `/data/gameserver/` is rebuilt from scratch on every start using `cp -as`. No FUSE or `SYS_ADMIN` required.
- **settings.py is the single source of truth** for path constants and env-derived config. All modules import paths from `enshctl.settings`.
- **Local imports in commands**: `commands/*.py` keeps `argparse`, `rich`, and `textual` imports local for fast CLI dispatch. Scoped `PLC0415` ignore.
- **Cron parsing**: `backup/core.py` `parse_cron()` converts cron expressions to seconds. Falls back to 1200s (20 min) if parsing fails.
- **Config system**: `ENSHROUDED_*` env vars → nested JSON in `enshrouded_server.json`. Double underscores delimit nesting. Array indexing via numeric segments.
- **DepotDownloader quirks**: See `docs/depotdownloader-quirks.md`. The `-manifestfile`/`-depotkeys` flags require the DepotDownloaderMod fork.
- **Archive format detection**: Based on file extension (`.tar.zst`, `.tar.gz`, `.zip`). Not content-sniffed.
- **Restore confirmation**: Interactive TUI restore requires Textual. Falls back to `input()` if unavailable.
- **Free space guards**: `INSTALL_MIN_FREE_SPACE` (10 GiB) blocks install. `BACKUP_MIN_FREE_SPACE_WARN` (2 GiB) and `BACKUP_MIN_FREE_SPACE_STOP` (1 GiB) control backup behavior.
- **PERSIST_FILES**: Comma-separated relative paths persisted to `/data/config/` and symlinked into the game tree. Path traversal entries are skipped.
- **Orchestrator logging**: `ORCHESTRATOR_LOG_FILE` enables file logging. `ORCHESTRATOR_LOG_LEVEL` controls level (default `WARNING`). Game server entries filtered out.
