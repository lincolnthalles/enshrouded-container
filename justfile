
@_default:
    just --list

# Build the project with uv
build:
    uv build

# Run tests with pytest
test *ARGS='':
    uv run pytest {{ ARGS }} src/tests/

# Lint the project with ruff
lint:
    uv run ruff check src/enshctl src/tests/

# Typecheck the project with pyrefly
typecheck:
    uv run pyrefly check 

# Run all validations (lint, typecheck, test)
validate *ARGS='':
    #!/usr/bin/env -S bash -euo pipefail
    uv run dprint check --list-different
    uv run pytest {{ ARGS }} src/tests/ 
    uv run ruff check src/enshctl src/tests/
    uv run pyrefly check --output-format=min-text

# Concise version of validate
@gate:
    just validate >/dev/null 2>&1 && echo "[OK] All validations passed." || echo "[ERROR] Run 'just validate' for more details."

# Clean project artifacts
clean:
    rm -rf __pycache__ .pytest_cache .ruff_cache .venv .pytest_cache dist enshrouded-data
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
    uv run dprint fmt

# Check code formatting
fmt-check:
    uv run dprint check

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
git-tag TAG:
    #!/usr/bin/env bash
    set +e
    TAG="v{{ trim_start_matches(TAG, 'v') }}"
    git push origin :refs/tags/$TAG
    git tag -d $TAG
    git tag -a $TAG -m "Release $TAG"
    git push origin $TAG

# Bump the package version. See <https://docs.astral.sh/uv/guides/package/#updating-your-version> for more info.
[group('maintainer-only')]
bump VALUE='major/minor/patch':
    #!/usr/bin/env bash
    echo "Current version: "$(uv version --short)""
    if [[ "{{ VALUE }}" == "major/minor/patch" ]]; then
        uv help version
        exit 0
    fi
    uv version --bump {{ VALUE }}

# Tag and push to GitHub, triggering the release workflow.
[confirm("Are you sure you want to publish a new release? Make sure you've bumped the version and pushed your changes.")]
[group('maintainer-only')]
publish: validate
    #!/usr/bin/env bash
    VERSION="$(uv version --short)
    echo "Publishing version "$VERSION"…"
    just git-tag "$VERSION"
    git push origin main
