"""Freeze the DAT-757 scorecard cells into the DAT-762 acceptance fixture.

One-shot builder (the `build_clean_bands.py` convention): rebuilds the three
RelBench OBTs with the scorecard's own machinery and writes, per cell, the
statistics the engine's dimension-identity ROUTING consumes — per-column
counts + seeded distinct-value samples (raw values, so the Tier-1 test derives
value-shape features through the ENGINE's own code, never a duplicated
feature definition) and the pair g3s — plus the stack's frozen C1 verdict and
the pre-registered truth label.

Output: calibration/fixtures/dimension_identity_cells.json (checked in).
Inputs: data/relbench/<ds>/ exports (re-derivable via
scripts/probes/dat757-relbench/fetch_export.py) + the frozen
scripts/probes/dat757-channel-ablation/{cells.py,results.json}.

Constructed cross-view cells (K/L) carry column stats only (no pair g3s — no
shared rows by construction); they are conform-judge targets, not routing
targets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts/probes/dat757-channel-ablation"))
sys.path.insert(0, str(ROOT / "scripts/probes/dat757-relbench"))

from cells import CELLS  # noqa: E402
from probe_ablation import load_all  # noqa: E402

OUT = ROOT / "calibration/fixtures/dimension_identity_cells.json"
RESULTS = ROOT / "scripts/probes/dat757-channel-ablation/results.json"
SAMPLE_DISTINCT = 200
SEED = 762


def _column_stats(obt: pl.DataFrame, col: str, rng: np.random.Generator) -> dict:
    s = obt.get_column(col)
    non_null = s.drop_nulls().cast(pl.Utf8)
    distinct = non_null.unique().sort()
    k = min(SAMPLE_DISTINCT, len(distinct))
    idx = rng.choice(len(distinct), size=k, replace=False) if k else np.array([], dtype=int)
    return {
        "n_rows": len(s),
        "n_distinct": int(non_null.n_unique()),
        "null_rate": round(float(s.null_count()) / max(1, len(s)), 4),
        "dtype": str(s.dtype),
        "sample_distinct_values": sorted(str(distinct[int(i)])[:120] for i in idx),
    }


def main() -> None:
    data = load_all()
    c1 = {
        key.split(":")[0]: entry
        for key, entry in json.loads(RESULTS.read_text()).items()
        if key.endswith(":C1")
    }
    rng = np.random.default_rng(SEED)

    frozen = []
    for cell in CELLS:
        entry: dict = {
            "id": cell.id,
            "klass": cell.klass,
            "dataset": cell.dataset,
            "a": cell.a,
            "b": cell.b,
            "truth": cell.truth,
            "why": cell.why,
            "c1_verdict": c1.get(cell.id, {}).get("verdict"),
            "c1_reason": c1.get(cell.id, {}).get("reason"),
        }
        if cell.dataset.startswith("constructed"):
            base = cell.dataset.split(":", 1)[1]
            obt = data[base][0]
            for side, col in (("a", cell.a), ("b", cell.b)):
                if col in obt.columns:
                    entry[f"col_{side}"] = _column_stats(obt, col, rng)
            frozen.append(entry)
            continue
        obt, _group, scan = data[cell.dataset]
        entry["col_a"] = _column_stats(obt, cell.a, rng)
        entry["col_b"] = _column_stats(obt, cell.b, rng)
        key, fwd = ((cell.a, cell.b), True) if (cell.a, cell.b) in scan.stats else (
            (cell.b, cell.a), False)
        ps = scan.stats.get(key)
        if ps is not None:
            g3f, g3b = (ps.g3_row_fwd, ps.g3_row_bwd) if fwd else (ps.g3_row_bwd, ps.g3_row_fwd)
            ef, eb = (ps.g3_eng_fwd, ps.g3_eng_bwd) if fwd else (ps.g3_eng_bwd, ps.g3_eng_fwd)
            entry["pair"] = {
                "g3_row_fwd": round(float(g3f), 6),
                "g3_row_bwd": round(float(g3b), 6),
                "g3_pair_fwd": round(float(ef), 6),
                "g3_pair_bwd": round(float(eb), 6),
            }
        frozen.append(entry)

    OUT.write_text(json.dumps(
        {
            "provenance": {
                "cells": "scripts/probes/dat757-channel-ablation/cells.py (frozen 2026-07-14)",
                "c1": "results.json C1 verdicts (the stack's own, graded round)",
                "builder": "scripts/build_dimension_identity_cells.py",
                "sample_seed": SEED,
                "sample_distinct": SAMPLE_DISTINCT,
            },
            "cells": frozen,
        },
        indent=1,
    ))
    routed = sum(1 for e in frozen if "pair" in e)
    print(f"froze {len(frozen)} cells ({routed} with pair stats) -> {OUT}")


if __name__ == "__main__":
    main()
