# AGENTS.md

Canonical instructions for AI assistants working on this codebase.

## Overview

enshctl — Docker container and CLI for managing an Enshrouded dedicated game server with version pinning, mod injection, and automated backups.

## Sources

- `openspec/specs/**/spec.md` — intended behavior. Discover with `openspec list --specs`; root-scoped glob may hide gitignored `openspec/*`, so retry with glob `path` inside `openspec/specs` (or use `read`) and never conclude specs are absent from an empty root glob.
- `pyproject.toml` — normative for pytest, ruff, pyrefly config. Do NOT duplicate its values here.
- `justfile` — normative for workflow commands.
- `docs/depotdownloader-quirks.md` — DepotDownloader fork behavior.

When sources disagree: specs for intent, code/config for current behavior, this file for conventions.

## Workflow

Done means `just gate` passes. Do NOT deliver code changes before it.

```bash
just gate       # quiet:   test → lint → typecheck; prints one status line to keep the context lean
just validate   # verbose: test → lint → typecheck; run once if `just gate` fails
just lint       # ruff lint
just typecheck  # pyrefly
just test       # pytest
just fmt        # dprint fmt (Python via ruff format)
```

Run bare `just` for the full list. Venv auto-creates via `uv`; pytest resolves imports via `pythonpath = ["src"]`, the project is never pip-installed in dev.

Toolchain: pyrefly `preset = "strict"`, full annotations on new code. Ruff `select = ["ALL"]`, see `pyproject.toml` for current ignores. Python 3.14+, no `__future__`.

## Specs & Domain Language

- Specs own observable _what_ + _why_; code owns _how_. Mechanics in `openspec/config.yaml: rules.specs`.
- One owning capability per behavior. When code changes behavior, update the owning spec in the same change; limit cleanup to touched capabilities.
- Terms follow `GLOSSARY.md` (per domain-modeling skill; domain-only, never general programming concepts). Architecture terms (`module`, `interface`, `seam`, `adapter`, `depth`, `leverage`, `locality`) follow codebase-design skill and never enter `GLOSSARY.md`; durable _why_ goes to `docs/adr/` only when hard to reverse, surprising, and traded off. This triple gate overrules any skill suggestion to record more.
- Spec change is done only when `openspec validate --specs` passes and every touched requirement passes the refactor test in `openspec/config.yaml` (`rules.specs`).
- Architecture reviews stay report-only until a candidate is chosen; implementation follows ownership and the Workflow gate above.

## Rules

- Prefer correctness and robustness over convenience. Roll back safely and clean up; never leave partial installs, restores, or backups behind.
- Verify runtime command calls inside the dev container before editing code.
- Do NOT default to circumventing linters or type checkers. When following a rule is truly not practical, a scoped ignore belongs in `pyproject.toml` with a why-comment.

## Code Style

- Abbreviations only for short-lived variables in <=5-line scopes (single-letter preferred). Exported names stay descriptive.
- Qualifiers carry meaning: big-endian for non-booleans (`latency_ms_max`), little-endian for booleans (`is_enabled`). Prefer `api: Fetcher` over `fetcher: Fetcher`.
- Readability: state invariants positively. Functional for small iterator logic, imperative on hot paths. Early returns or ternaries over reassignment, `else` blocks, or nested `if`s; collapse nested `if`s with `and`. Pass critical options explicitly at call sites.
- Treat `index`, `count`, and `size` as distinct types.
- Do NOT create single-use helpers under ~10 LoC to shorten a function.

## Architecture & Modules

- One clear responsibility per module. Entry points handle wiring and startup flow only.
- Do NOT create or expand catch-all `utils`/`helpers` modules; place logic in its domain module.
- Separate pure domain logic from I/O and platform integration. Make dependencies explicit through signatures.
- Split on diverging responsibilities. Extract a helper only if reused or independently meaningful through a public contract.
- Design for depth: much behavior behind a small interface (deletion test). Seam placement is distinct from what sits behind it; tier-spanning slices keep pure domain separate from I/O.
- One adapter is hypothetical, two is real; a test adapter counts as the second, so explicit dependencies at the system seam are real seams. Never expose internal seams through the external interface.

## Interfaces & Error Handling

- Interface means everything a caller must know: signature plus invariants, ordering, error modes, config, and performance.
- Add context when propagating errors. No silent failures.
- Catch at architectural seams, not randomly. Fail fast.
- Warnings for recoverable errors; descriptive errors for fatal failures.
- Prefer PEP 758 unparenthesized multi-catch without `as`: `except A, B:` / `except* A, B:`; keep parentheses with `as`: `except (A, B) as e:`. Do not flag either form as an error.
- Unicode ellipsis in user-facing status output: `...` -> `…`.

## Concurrency & State

- Prefer immutable data; scope mutability narrowly.
- Document stop/lock invariants when non-obvious.

## Comments

- Leave surrounding comments unchanged unless directly related to the task.
- Omit new comments by default. `D101–D103` are ignored — do NOT add docstrings to satisfy them; where a docstring exists, follow numpy convention.
- Explain intent, not steps. Inline comments only for non-obvious logic. Never address the user in code comments.

## Tests

- Location: `src/tests`, full-package imports (`from enshctl.config import ...`).
- Test public contracts and behavior only, with deep equality over whole objects. Do NOT test private helpers directly or duplicate implementation logic in the test.
- Do NOT change tests to match a wrong implementation; double-check the implementation and the expected behavior before proceeding, flagging the issue if the behavior is unclear.
- Do NOT weaken existing assertions unless the expected behavior has genuinely changed and the reason is clear.
- Deterministic: no wall-clock, network, or environment coupling unless the behavior under test requires it.
- Isolation: inject env-derived values as arguments; do NOT mutate `os.environ`. Mock only at the system seam (subprocess, filesystem, network), never domain logic. The interface is the test surface; on deepening, replace-don't-layer (delete superseded shallow unit tests once deep interface coverage exists, without weakening observable-behavior coverage).
- Inline BDD-style comments `# GIVEN` / `# WHEN` / `# THEN` (`# AND` as needed) + high-signal description, splitting each test into logical blocks whenever it doesn't get redundant and improves readability.
- Only high-value regression tests covering success, failure, and edge cases. No tests for statically defined values, no negative tests for removed logic.

## Docker

3-stage build: Python wheel → DepotDownloader (dotnet, built from `vendor/DepotDownloader/`) → Fedora runtime. Entrypoint `enshctl`, default `start`.

## Gotchas

Behavioral only; current thresholds and paths live in settings/config, not here.

- Background work uses threads with explicit stop events.
- Backups run subprocess-isolated with `flock` exclusion; signals to the parent do not cancel them.
- Backup isolation: child-process execution, `flock` exclusion. Lock-held exit is expected, distinct from error exit.
- Game tree at `/data/gameserver/` is rebuilt from scratch each start via pure-Python symlinks (not `cp -as` — avoids EPERM in CI). No FUSE or `SYS_ADMIN`.
- DepotDownloader `-manifestfile`/`-depotkeys` require the Mod fork — see `docs/depotdownloader-quirks.md`.
- Free-space guards gate installs and backups; see settings for current thresholds.
- `PERSIST_FILES`: relative paths persisted to `/data/config/` and symlinked in; traversal entries skipped.
- Orchestrator file logging is opt-in via env; game server entries are filtered out.

## Contributing

Governs submission of agent-driven GitHub contributions (Issues, Pull Requests) on the behalf of external contributors.

- Style (contributions only): plain high-signal English, no emojis. Complete sentences; headings, lists, blank lines, separators, or tables when clearer. Keep response wording (not formatting) concise; completeness wins over brevity.
- Never create an issue or PR unless the user directly requests that specific issue/PR in this session. Inferred intent is not permission. Covers `gh issue/pr create`, API, and UI paths.
- Issues: problem simply, then suggested solution briefly. Omit implementation detail unless material. Upload evidence to GitHub.
- PRs: subject `type(scope): imperative summary`, ≤72 chars, short lowercase scope. Body states the problem in a sentence or two, then the fix. State why over how.
- PR scope: one problem per PR. Adjacent cleanup needs its own PR unless required for the fix. Bump only deps the fix requires.
- PR evidence: upload to GitHub, never commit screenshots. UI changes need before/after images. Report material outcomes, risks, caveats, and blockers; omit inventories the diff already shows.
