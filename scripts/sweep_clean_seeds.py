"""Clean seed-sweep driver — regenerates the input to `build_clean_bands.py` (the A4 rig).

For each seed: generate the clean corpus at that seed and run the pipeline in its OWN
isolated workspace, then dump per-grain detector scores to `output/seed_sweep/seed_<seed>.yaml`
in the exact key format `build_clean_bands.py` / `test_detector_precision._scored_keys`
expect (`{table}.{column}:{detector}` for column/relationship, `{table}:{detector}` for
table). `build_clean_bands.py` then aggregates [min, max, seen] across the dumps.

Rebuilt 2026-06-22 (DAT-540 fallout): the original `scripts/probes/a4-seed-sweep` driver
was deleted as a probe, leaving `build_clean_bands.py` (the reader) with no producer. This
lives in `scripts/` as a RIG, not a probe — rerun it whenever the clean bands must be
resweept (a detector/loss change that should move a clean band, e.g. the
slice_conditional_null demote + the DAT-536 dimensional_entropy silence).

ISOLATION (no `clean-pg`): each seed runs as a DISTINCT strategy name → a DISTINCT
workspace (`workspace_id_for(strategy)`, 596d40c), so seeds never share a workspace and
their content-keyed file sources can't accumulate/mix. This is the same isolation the
add_source calibration queue relies on — the stack stays UP the whole sweep (no `down -v`,
which would wipe Temporal's own Postgres-backed persistence and destabilise it mid-run).
Seed 0 uses the real `clean` strategy so a live `clean` run remains for the precision test
to read; the rest use throwaway `clean.yaml` copies that are removed at the end.

    uv run python scripts/sweep_clean_seeds.py                 # seeds 46 47 48
    uv run python scripts/sweep_clean_seeds.py --seeds 46 47   # custom seeds
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).resolve().parent.parent
SWEEP_DIR = EVAL_ROOT / "output" / "seed_sweep"
STRATEGIES_DIR = EVAL_ROOT / "strategies"
BASE_STRATEGY = "clean"


def _run(args: list[str]) -> None:
    """Run a subprocess from the eval root, streaming output; raise on failure."""
    print(f"  $ {' '.join(args)}", flush=True)
    subprocess.run(args, cwd=EVAL_ROOT, check=True)


def _ensure_stack_ready(timeout: float = 120.0) -> None:
    """Bring the eval stack up ONCE and block until the published ports accept connections."""
    from calibration import stack

    stack.up()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stack._temporal_ready() and stack._pg_ready() and stack._seaweedfs_ready():
            print("  [stack] Temporal + PG + SeaweedFS accepting connections", flush=True)
            return
        time.sleep(2)
    raise SystemExit(f"eval stack not ready after {timeout:.0f}s")


def _scored_keys_for_dump(strategy: str) -> dict[str, dict[str, float]]:
    """Per-grain {key: score} for ``strategy``'s completed run, matching the band-key format.

    Mirrors `test_detector_precision._scored_keys` exactly so the dump and the precision
    guard speak the same keys. Read in-process from the just-completed run's sidecar.
    """
    from calibration.conftest import _load_scores_for_strategy

    scores = _load_scores_for_strategy(strategy)
    return {
        "column": {f"{t}.{c}:{d}": s for (t, c, d), s in scores.column.items()},
        "table": {f"{t}:{d}": s for (t, d), s in scores.table.items()},
        "relationship": {f"{t}.{c}:{d}": s for (t, c, d), s in scores.relationship.items()},
    }


def _strategy_for(index: int, seed: int) -> tuple[str, Path | None]:
    """Seed 0 → the real `clean` strategy (so a live clean run survives for the precision
    test); later seeds → a throwaway `clean.yaml` copy. Returns (name, temp_path|None)."""
    if index == 0:
        return BASE_STRATEGY, None
    name = f"clean-sweep-{seed}"
    path = STRATEGIES_DIR / f"{name}.yaml"
    path.write_text((STRATEGIES_DIR / f"{BASE_STRATEGY}.yaml").read_text())
    return name, path


def sweep_seed(strategy: str, seed: int) -> Path:
    """Generate + pipeline the clean corpus at one seed in its own workspace, dump scores."""
    print(f"[sweep] seed {seed} (strategy {strategy})", flush=True)
    _run(["uv", "run", "python", "-m", "calibration.runner", strategy,
          "--generate-only", "--seed", str(seed)])
    _run(["uv", "run", "python", "-m", "calibration.runner", strategy, "--pipeline-only"])

    doc: dict[str, Any] = {"seed": seed, **_scored_keys_for_dump(strategy)}
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    out = SWEEP_DIR / f"seed_{seed}.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False))
    n = {g: len(doc[g]) for g in ("column", "table", "relationship")}
    print(f"[sweep] seed {seed} → {out} ({n})", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[46, 47, 48])
    args = parser.parse_args()

    _ensure_stack_ready()
    temp_files: list[Path] = []
    try:
        for i, seed in enumerate(args.seeds):
            strategy, temp = _strategy_for(i, seed)
            if temp is not None:
                temp_files.append(temp)
            sweep_seed(strategy, seed)
    finally:
        for p in temp_files:
            p.unlink(missing_ok=True)
        if temp_files:
            print(f"[sweep] removed {len(temp_files)} temp strategy file(s)", flush=True)
    print(f"[sweep] done — {len(args.seeds)} seed(s). Now: "
          f"uv run python scripts/build_clean_bands.py", flush=True)


if __name__ == "__main__":
    main()
