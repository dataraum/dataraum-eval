"""Post-fix clean resweep (disposable probe): seeds 46/47/48 with the fixed specs.

The A4 sweep (seeds 42-45) measured clean bands BEFORE the stage_date_ordering
hint fix (engine c98f00fd) — its wide cross_table bands on invoices/payments
date columns document the pre-fix flap. This resweep replaces the sweep corpus
wholesale under the fixed spec (and the derived_value identity-conflict score
shape): pre-fix dumps are archived to output/seed_sweep_prefix/, three post-fix
seeds are dumped fresh, and the bands rebuild from the post-fix corpus only.

After it finishes: scripts/build_clean_bands.py, then
scripts/dump_intent_readiness.py to rebaseline clean readiness (review diff —
the date/id columns should clear; LLM-wobble columns get documented).

    caffeinate -dims uv run python scripts/probes/postfix-resweep/run_resweep.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

EVAL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(EVAL_ROOT))

from calibration import outcomes  # noqa: E402
from calibration import runner as runner_mod  # noqa: E402
from calibration.conftest import _load_scores_for_strategy  # noqa: E402

OUT = EVAL_ROOT / "output" / "seed_sweep"
ARCHIVE = EVAL_ROOT / "output" / "seed_sweep_prefix"
STRATEGY = "clean"
SEEDS = (46, 47, 48)


def _dump(seed: int) -> None:
    scores = _load_scores_for_strategy(STRATEGY)
    doc = {
        "seed": seed,
        "reran_pipeline": True,
        "post_fix": "stage_date_ordering hint (engine c98f00fd) + derived identity-conflict score",
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
    print(f"[resweep] seed {seed}: {len(doc['column'])} column scores dumped", flush=True)


def main() -> None:
    if OUT.exists() and not ARCHIVE.exists():
        ARCHIVE.mkdir(parents=True)
        for f in sorted(OUT.glob("seed_*.yaml")):
            shutil.move(str(f), ARCHIVE / f.name)
        print(f"[resweep] archived pre-fix dumps -> {ARCHIVE}", flush=True)

    for seed in SEEDS:
        print(f"[resweep] generate {STRATEGY} seed={seed}", flush=True)
        runner_mod.generate(STRATEGY, seed=seed)
        print(f"[resweep] pipeline {STRATEGY} seed={seed} (Temporal + LLM)", flush=True)
        runner_mod.run_pipeline(STRATEGY)
        _dump(seed)

    print("[resweep] done — rebuild bands + readiness baseline next", flush=True)


if __name__ == "__main__":
    main()
