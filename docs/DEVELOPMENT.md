# Development Setup

This guide covers how to set up a working environment.

## Requirements

- [`uv`](https://github.com/astral-sh/uv) for dependency and virtual environment management.
- [`just`](https://github.com/casey/just) for workflow commands.
- [`openspec`](https://github.com/Fission-AI/OpenSpec/) for tracking agent-driven changes in user-observable behavior.
- [Docker](https://docs.docker.com/engine/install/) 24 or later, preferably on a native Linux host.
- UDP port `15637` reachable and the game client installed for live testing.

If [Homebrew](https://brew.sh/) is available in your system:

```bash
brew install uv just openspec
```

> [!TIP]
> Tools not listed above, like `dprint`, `pyrefly`, `ruff`, and even Python itself, are handled transparently by `uv`.

## Repository Setup

```bash
git clone https://github.com/lincolnthalles/enshrouded-container.git
cd enshrouded-container
git checkout -b my-branch
uv sync     # install dependencies
just        # print available project commands
```

## Hot-paths

| Path               | Purpose                                                                                                          |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `src/enshctl/`     | Container orchestrator CLI, entrypoint `enshctl`, default `start`                                                |
| `src/tests/`       | Pytest suite                                                                                                     |
| `openspec/specs/`  | Intended behavior by capability, one owning capability per behavior                                              |
| `docs/`            | User docs, quirks, environment reference, and `docs/adr/` decisions                                              |
| `docs/GLOSSARY.md` | Canonical domain terms                                                                                           |
| `Dockerfile`       | Three-stage build: Python wheel, DepotDownloader, Fedora runtime                                                 |
| `deploy/`          | Runnable samples: `docker-compose.yml` + `enshrouded.env` (prod), `docker-compose.dev.yml` (dev, via `just dev`) |
