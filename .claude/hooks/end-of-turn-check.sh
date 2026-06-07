#!/bin/bash
# End-of-turn quality gate for Claude Code
# Exit code 2 = block and show error to Claude (forces it to fix)
# Exit code 0 = success, continue

set -e

cd "$CLAUDE_PROJECT_DIR/"

echo "Running quality checks..."

# --- Eval repo checks ---
echo "Checking: ruff (calibration)..."
if ! uv run ruff check calibration/ --quiet 2>/dev/null; then
    echo "ruff check failed on calibration/. Fix lint errors before continuing." >&2
    exit 2
fi

echo "Checking: mypy (calibration)..."
if ! uv run mypy calibration/ --no-error-summary 2>/dev/null; then
    echo "Type checking failed on calibration/. Fix type errors before continuing." >&2
    exit 2
fi

# --- Vendor dataraum-context engine checks (use its own ruff config) ---
# The vendor repo is a monorepo since DAT-339: the engine lives at
# packages/engine (src/ at the root no longer exists).
CONTEXT_DIR="$CLAUDE_PROJECT_DIR/vendor/dataraum-context/packages/engine"
if [ -d "$CONTEXT_DIR" ]; then
    pushd "$CONTEXT_DIR" > /dev/null

    echo "Checking: ruff (dataraum-context engine)..."
    if ! uv run ruff check src/ --quiet 2>/dev/null; then
        echo "ruff check failed on vendor/dataraum-context/packages/engine/src/. Fix lint errors before continuing." >&2
        popd > /dev/null
        exit 2
    fi

    echo "Checking: ruff format (dataraum-context engine)..."
    if ! uv run ruff format --check src/ --quiet 2>/dev/null; then
        echo "ruff format check failed on vendor/dataraum-context/packages/engine/src/. Run ruff format." >&2
        popd > /dev/null
        exit 2
    fi

    popd > /dev/null
fi

echo "All quality checks passed."
exit 0
