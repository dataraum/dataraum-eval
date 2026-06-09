"""Regenerate a strategy's data dir (direct testdata API via the eval env).

Usage: uv run python scripts/regen_data.py <strategy> [seed] [months]
"""

from __future__ import annotations

import sys

from calibration.runner import generate

strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
months = int(sys.argv[3]) if len(sys.argv) > 3 else 12

out = generate(strategy, seed=seed, months=months)
print(f"[regen] {strategy} -> {out}")
