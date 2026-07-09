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
EVERY seed uses a throwaway `clean.yaml` copy (removed at the end) — the live `clean`
workspace is never re-entered (single-flight workflow ids + the DAT-639 changed-content
witness skip; see `_strategy_for`). The precision test reads the gate's own clean run.

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


def _strategy_for(seed: int) -> tuple[str, Path]:
    """Every seed → a throwaway `clean.yaml` copy in its OWN fresh workspace.

    Seed 0 used to reuse the real `clean` strategy so a live run survived for
    the precision test. Isolation is correct for two reasons (DAT-665 resolved
    the original "child-id collision" read as a misdiagnosis — completed-id
    re-runs work as designed): (1) deterministic workflow ids are single-flight,
    so a leftover still-RUNNING workflow from an interrupted attempt rejects the
    restart; (2) DAT-639's source-level witness skip means re-adding CHANGED
    bytes at the same URIs silently keeps the previously-ingested data — a
    same-workspace resweep would measure the OLD seed even when it "succeeds".
    The live `clean` run comes from the calibration gate itself; bands are
    cross-seed by design, so the sweep never needs to touch that workspace.
    """
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


def dump_completed(strategy: str, seed: int) -> Path:
    """Dump an ALREADY-completed run's scores as a sweep seed — no re-pipeline.

    Budget-sensitive resweep: after a well-understood change, an existing run (e.g.
    the calibration gate's own ``clean`` run) is a valid seed, so it can be folded
    in instead of spending a fresh pipeline for it. The reused run is a distinct
    seed of the same corpus; the band is still [min, max] across all dumps.
    """
    doc: dict[str, Any] = {"seed": seed, **_scored_keys_for_dump(strategy)}
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    out = SWEEP_DIR / f"seed_{seed}.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"[sweep] reused completed {strategy!r} → {out}", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[46, 47, 48])
    parser.add_argument(
        "--reuse",
        nargs="*",
        default=[],
        metavar="STRATEGY:SEED",
        help="Fold an already-completed run in as a seed (no re-pipeline), e.g. "
        "'clean:0' to reuse the gate's clean run — budget-sensitive resweep.",
    )
    args = parser.parse_args()

    _ensure_stack_ready()
    for entry in args.reuse:
        strat, _, seed_s = entry.partition(":")
        dump_completed(strat, int(seed_s))
    temp_files: list[Path] = []
    try:
        for seed in args.seeds:
            strategy, temp = _strategy_for(seed)
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
