# AGENTS.md

Canonical instructions for AI assistants working on this codebase.

## Overview

enshctl — Docker container and CLI for managing an Enshrouded dedicated game server with version pinning, mod injection, and automated backups.

## Sources

- `openspec/specs/**/spec.md` — intended behavior. Discover with `openspec list --specs`; root-scoped glob may hide gitignored `openspec/*`, so retry with glob `path` inside `openspec/specs` (or use `read`) and never conclude specs are absent from an empty root glob.
- `pyproject.toml` — normative for pytest, ruff, pyrefly config. Do not duplicate its values here.
- `justfile` — normative for workflow commands.
- `docs/depotdownloader-quirks.md` — DepotDownloader fork behavior.

When sources disagree: specs for intent, code/config for current behavior, this file for conventions.

## Workflow

Done means `just gate` passes. Do not deliver code changes before it.

```bash
just gate         # test → lint → typecheck, concise output
just validate     # test → lint → typecheck in sequence
just fmt          # dprint fmt (Python via ruff format)
```

Run bare `just` for the full list. Venv auto-creates via `uv`; pytest resolves imports via `pythonpath = ["src"]`, the project is never pip-installed in dev.

Toolchain: pyrefly `preset = "strict"`, full annotations on new code. Ruff `select = ["ALL"]`, see `pyproject.toml` for current ignores. Python 3.14+, no `__future__`.

## Rules

- Do NOT circumvent linters or type checkers. A scoped ignore belongs in `pyproject.toml` with a why-comment.
- Verify runtime command calls inside the dev container before editing code.
- Prefer correctness and robustness over convenience. Roll back safely and clean up; never leave partial installs, restores, or backups behind.

## Code Style

- Abbreviations only for short-lived variables in <=5-line scopes (single-letter preferred). Exported names stay descriptive.
- Qualifiers carry meaning: big-endian for non-booleans (`latency_ms_max`), little-endian for booleans (`is_enabled`). Prefer `api: Fetcher` over `fetcher: Fetcher`.
- Readability: state invariants positively. Functional for small iterator logic, imperative on hot paths. Early returns or ternaries over reassignment, `else` blocks, or nested `if`s; collapse nested `if`s with `and`. Pass critical options explicitly at call sites.
- Do NOT create single-use helpers under ~10 LoC to shorten a function.
- Treat `index`, `count`, and `size` as distinct types.

## Architecture & Modules

- One clear responsibility per module. Entry points handle wiring and startup flow only.
- Do not create or expand catch-all `utils`/`helpers` modules; place logic in its domain module.
- Separate pure domain logic from I/O and platform integration. Make dependencies explicit through signatures.
- Split on diverging responsibilities. Extract a helper only if reused or independently meaningful through a public contract.

## API & Error Handling

- Add context when propagating errors. No silent failures.
- Catch at architectural boundaries, not randomly. Fail fast.
- Warnings for recoverable errors; descriptive errors for fatal failures.
- Unicode ellipsis in user-facing status output: `...` -> `…`.

## Concurrency & State

- Prefer immutable data; scope mutability narrowly.
- Background work uses threads with explicit stop events.
- Backups run subprocess-isolated with `flock` exclusion; signals to the parent do not cancel them. Document stop/lock invariants when non-obvious.

## Comments

- Leave surrounding comments unchanged unless directly related to the task.
- Omit new comments by default. `D101–D103` are ignored — do not add docstrings to satisfy them; where a docstring exists, follow numpy convention.
- Explain intent, not steps. Inline comments only for non-obvious logic. Never address the user in code comments.

## Tests

- Location: `src/tests`, full-package imports (`from enshctl.config import ...`). No conftest, no fixtures.
- Test public contracts and behavior only, with deep equality over whole objects. Do not test private helpers directly or duplicate implementation logic in the test.
- Deterministic: no wall-clock, network, or environment coupling unless the behavior under test requires it.
- Isolation: inject env-derived values as arguments; do not mutate `os.environ`. Mock only at the system boundary (subprocess, filesystem, network), never domain logic.
- Mark with `# GIVEN` / `# WHEN` / `# THEN` (`# AND` as needed).
- Only high-value regression tests covering success, failure, and edge cases. No tests for statically defined values, no negative tests for removed logic.

## Docker

3-stage build: Python wheel → DepotDownloader (dotnet, built from `vendor/DepotDownloader/`) → Fedora runtime. Entrypoint `enshctl`, default `start`.

## Gotchas

Behavioral only; current thresholds and paths live in settings/config, not here.

- Backup isolation: child-process execution, `flock` exclusion. Lock-held exit is expected, distinct from error exit.
- Game tree at `/data/gameserver/` is rebuilt from scratch each start via pure-Python symlinks (not `cp -as` — avoids EPERM in CI). No FUSE or `SYS_ADMIN`.
- DepotDownloader `-manifestfile`/`-depotkeys` require the Mod fork — see `docs/depotdownloader-quirks.md`.
- Free-space guards gate installs and backups; see settings for current thresholds.
- `PERSIST_FILES`: relative paths persisted to `/data/config/` and symlinked in; traversal entries skipped.
- Orchestrator file logging is opt-in via env; game server entries are filtered out.

## Contributing

Agent-driven GitHub contributions on the user's behalf. No `CONTRIBUTING.md` or `.github/` templates.

- Style (contributions only): plain high-signal English, no emojis. Complete sentences; headings, lists, or tables when clearer. Keep responses concise; completeness wins over brevity.
- Never create an issue or PR unless the user directly requests that specific issue/PR in this session. Inferred intent is not permission. Covers `gh issue/pr create`, API, and UI paths.
- Issues: problem simply, then suggested solution briefly. Omit implementation detail unless material. Upload evidence to GitHub.
- PRs: subject `type(scope): imperative summary`, ≤72 chars, short lowercase scope. Body states the problem in a sentence or two, then the fix. State why over how.
- PR scope: one problem per PR. Adjacent cleanup needs its own PR unless required for the fix. Bump only deps the fix requires.
- PR evidence: upload to GitHub, never commit screenshots. UI changes need before/after images. Report material outcomes, risks, caveats, and blockers; omit inventories the diff already shows.
