#!/bin/bash
# End-of-turn quality gate for Claude Code
# Exit code 2 = block and show error to Claude (forces it to fix)
# Exit code 0 = success, continue

set -e

cd "$CLAUDE_PROJECT_DIR/"

echo "Running quality checks..."

# Run ruff linter on calibration code
echo "Checking: ruff..."
if ! uv run ruff check calibration/ --quiet 2>/dev/null; then
    echo "ruff check failed. Fix lint errors before continuing." >&2
    exit 2
fi

# Run mypy on calibration code
echo "Checking: mypy..."
if ! uv run mypy calibration/ --no-error-summary 2>/dev/null; then
    echo "Type checking failed. Fix type errors before continuing." >&2
    exit 2
fi

echo "All quality checks passed."
exit 0
