## Purpose

Multi-stage Docker build producing and installing the project wheel via uv.

## Requirements

### Requirement: Builder produces wheel

A builder stage SHALL produce a Python wheel from the project source via `uv build`.

#### Scenario: Builder stage produces wheel

- **WHEN** the image is built
- **THEN** a builder stage SHALL run the project build and produce a `.whl` file

### Requirement: Final image installs wheel

The final stage SHALL install the built wheel into the runtime Python environment with all declared dependencies available. No raw source SHALL be copied into the final image; the package SHALL be installed as a proper Python package. The `zstandard` module SHALL be importable at module top level. UI display libraries are optional at runtime: their absence SHALL degrade output gracefully instead of failing.

#### Scenario: Final stage installs wheel

- **WHEN** the final image is built
- **THEN** it SHALL install the wheel from the builder stage with all declared dependencies

#### Scenario: zstandard importable at module level

- **WHEN** Python code in the container imports `zstandard` at module top level
- **THEN** the import SHALL succeed without `ImportError`

### Requirement: Entry point script

The container SHALL start via the installed `enshctl` console script as its entrypoint.

#### Scenario: Container entrypoint uses installed script

- **WHEN** the container starts
- **THEN** the entrypoint SHALL invoke the installed `enshctl` console script
