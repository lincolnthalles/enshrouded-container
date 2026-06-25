export ACTIVATE_VENV := "source " + justfile_directory() + "/.venv/bin/activate"

@_default:
    just --list

[private]
_ensure_venv:
    #!/usr/bin/env -S bash -euo pipefail
    if ! command -v uv &> /dev/null; then
        echo "uv not found! Install it from https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    if [ ! -d "./.venv" ]; then
        uv venv
    fi      
    $ACTIVATE_VENV
    uv sync --no-install-project

# Run tests with pytest
test *ARGS='': _ensure_venv
    $ACTIVATE_VENV && pytest {{ ARGS }} src/tests/

# Lint the project with ruff
lint: _ensure_venv
    $ACTIVATE_VENV && ruff check src/enshctl src/tests/

# Typecheck the project with pyrefly
typecheck: _ensure_venv
    $ACTIVATE_VENV && pyrefly check 

# Run all validations (lint, typecheck, test)
validate *ARGS='': _ensure_venv
    #!/usr/bin/env -S bash -euo pipefail
    $ACTIVATE_VENV
    pytest {{ ARGS }} src/tests/ 
    ruff check src/enshctl src/tests/
    pyrefly check --output-format=min-text

# Concise version of validate
@gate:
    just validate >/dev/null 2>&1 && echo "[OK] All validations passed." || echo "[ERROR] Run 'just validate' for more details."

# Build the project with uv
build:
    uv build

# Clean project artifacts
clean:
    rm -rf __pycache__ .pytest_cache .ruff_cache .venv .pytest_cache dist
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name '*.pyc' -delete 2>/dev/null || true
    echo "Cleaning Docker…"
    docker builder prune -f
    docker buildx prune -f 2>/dev/null || true
    docker container rm dev-enshrouded-server || true
    docker image rm dev-enshrouded-server-container || true
    docker image prune -f

# Format code
fmt:
    dprint fmt

[group('test container')]
dev:
    docker compose -f docker-compose.dev.yml up -d --build --force-recreate
    docker logs dev-enshrouded-server -f

[group('test container')]
dev-debug-config:
    docker compose -f docker-compose.dev.yml run --build --rm enshrouded debug-config

[group('test container')]
dev-version-info:
    docker compose -f docker-compose.dev.yml run --build --rm enshrouded version-info

[private]
git-retag TAG:
    #!/usr/bin/env bash
    set +e
    TAG="v{{ trim_start_matches(TAG, 'v') }}"
    git push origin :refs/tags/$TAG
    git tag -d $TAG
    git tag -a $TAG -m "Tag $TAG"
    git push origin $TAG

# Tag and push to GitHub, triggering the release workflow.
publish TAG: validate
    #!/usr/bin/env bash
    TAG="v{{ trim_start_matches(TAG, 'v') }}"
    just git-retag "$TAG"
    git push origin main
