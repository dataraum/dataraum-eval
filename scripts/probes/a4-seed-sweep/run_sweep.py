"""A4 seed sweep (disposable probe): clean-strategy detector scores across seeds.

Collects the raw material for measured clean score BANDS per detector — the
replacement for the captured single-run clean_baseline.yaml. Dumps the existing
seed-42 clean run's scores first (no rerun; the batch-2 run is still the live
sidecar), then for each new seed: generate clean data, run the pipeline
(Temporal + real LLM), dump scores + outcomes.

Output: output/seed_sweep/seed_<n>.yaml. Band analysis happens after collection —
this script only collects; it never aggregates or filters.

    caffeinate -dims uv run python scripts/probes/a4-seed-sweep/run_sweep.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import yaml

EVAL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(EVAL_ROOT))

from calibration import outcomes  # noqa: E402
from calibration import runner as runner_mod  # noqa: E402
from calibration.conftest import _load_scores_for_strategy  # noqa: E402

OUT = EVAL_ROOT / "output" / "seed_sweep"
STRATEGY = "clean"
NEW_SEEDS = (43, 44, 45)


def _dump(seed: int, *, reran_pipeline: bool) -> None:
    scores = _load_scores_for_strategy(STRATEGY)
    doc = {
        "seed": seed,
        "reran_pipeline": reran_pipeline,
        "column": {f"{t}.{c}:{d}": round(s, 4) for (t, c, d), s in sorted(scores.column.items())},
        "table": {f"{t}:{d}": round(s, 4) for (t, d), s in sorted(scores.table.items())},
        "view": {f"{v}:{d}": round(s, 4) for (v, d), s in sorted(scores.view.items())},
        "relationship": {
            f"{t}.{c}:{d}": round(s, 4) for (t, c, d), s in sorted(scores.relationship.items())
        },
        "outcomes": outcomes.label(STRATEGY),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"seed_{seed}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    print(
        f"[sweep] seed {seed}: {len(doc['column'])} column scores -> seed_{seed}.yaml", flush=True
    )


def main() -> None:
    try:
        _dump(42, reran_pipeline=False)
    except Exception:
        # The seed-42 sidecar/stack may be stale; the sweep itself is still valid
        # on the three fresh seeds. Record and continue.
        print("[sweep] seed 42 dump FAILED (continuing with fresh seeds):", flush=True)
        traceback.print_exc()

    for seed in NEW_SEEDS:
        print(f"[sweep] generate {STRATEGY} seed={seed}", flush=True)
        runner_mod.generate(STRATEGY, seed=seed)
        print(f"[sweep] pipeline {STRATEGY} seed={seed} (Temporal + LLM)", flush=True)
        runner_mod.run_pipeline(STRATEGY)
        _dump(seed, reran_pipeline=True)

    print("[sweep] done", flush=True)


if __name__ == "__main__":
    main()
