### Requirement: Multi-stage Docker build with uv

The Dockerfile SHALL use a multi-stage build. A builder stage SHALL use `uv build` to produce a Python wheel from the project source. The final stage SHALL install the wheel into the runtime Python environment.

#### Scenario: Builder stage produces wheel

- **WHEN** `docker build` is executed
- **THEN** a builder stage SHALL run `uv build` against the project source and produce a `.whl` file

#### Scenario: Final stage installs wheel

- **WHEN** the final Docker stage is built
- **THEN** it SHALL copy the wheel from the builder stage and install it, ensuring all declared dependencies (including `zstandard`) are available at runtime

#### Scenario: No raw source copy in final image

- **WHEN** the final image is inspected
- **THEN** there SHALL be no `/scripts/` directory containing raw Python source files; the package SHALL be installed as a proper Python package

### Requirement: Runtime dependency availability

All dependencies declared in `pyproject.toml` SHALL be installed in the final Docker image. The `zstandard` module SHALL be importable at the top level without fallback logic.

#### Scenario: zstandard is importable at module level

- **WHEN** Python code in the container imports `zstandard`
- **THEN** the import SHALL succeed without `ImportError` or deferred import patterns

### Requirement: Entry point script

The `pyproject.toml` SHALL declare a `[project.scripts]` entry point that maps `enshrouded-server` to the main CLI function. The Dockerfile `ENTRYPOINT` SHALL use this script name instead of `python3 /scripts/entrypoint.py`.

#### Scenario: Container entrypoint uses installed script

- **WHEN** the container starts
- **THEN** the `ENTRYPOINT` SHALL invoke `enshrouded-server` (the installed console script) rather than `python3 /scripts/entrypoint.py`

#### Scenario: Console script resolves to correct function

- **WHEN** `enshrouded-server` is executed
- **THEN** it SHALL resolve to `enshrouded_server.__main__:main` as declared in `pyproject.toml`
