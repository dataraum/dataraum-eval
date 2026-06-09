"""Ms-level recall+precision check for unit_consistency, on REAL testdata.

Reads the clean vs scale-mixed ``amount`` columns straight off the generated CSVs
(no pipeline) and runs ``measure_unit_consistency`` on each, for both the abstaining
(no declared unit) and the declared-unit (confidence 1.0) cases. Prints the pooled
conflict C, ignorance U, posterior, and the raw log-magnitude bimodality coefficient.

This is the eval-reset philosophy in action: prove the measure separates injection
from clean in milliseconds, and SEE the clean baseline (the natural-multimodality
false-positive risk) before committing to a 10-minute pipeline run. Observation only
— no thresholds asserted, nothing tuned.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from dataraum.entropy.measurements.unit_consistency import (
    bimodality_coefficient,
    measure_unit_consistency,
)

DATA = Path(__file__).resolve().parent.parent / "data"


def read_amount(strategy: str, table: str, col: str = "amount") -> list[float]:
    path = DATA / strategy / f"{table}.csv"
    out: list[float] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            v = row.get(col)
            if v in (None, ""):
                continue
            try:
                out.append(float(v))
            except ValueError:
                continue  # a non-numeric cell (shouldn't happen for a scale mix)
    return out


def _bc(values: list[float]) -> float:
    logs = [math.log10(abs(v)) for v in values if v not in (0, None)]
    return bimodality_coefficient(logs)


def _exponent_hist(values: list[float]) -> dict[int, int]:
    h: dict[int, int] = {}
    for v in values:
        if v in (0, None):
            continue
        e = int(math.floor(math.log10(abs(v))))
        h[e] = h.get(e, 0) + 1
    return dict(sorted(h.items()))


def _quantiles(values: list[float]) -> str:
    logs = sorted(math.log10(abs(v)) for v in values if v not in (0, None))
    if not logs:
        return "—"
    qs = [logs[int(p * (len(logs) - 1))] for p in (0.0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)]
    return "  ".join(f"{q:.2f}" for q in qs)


def report(label: str, values: list[float]) -> None:
    print(f"\n### {label}  (n={len(values)})")
    print(f"  log10|v| bimodality coefficient = {_bc(values):.4f}  (unimodal≈0.33, uniform≈0.555)")
    print(f"  log10|v| quantiles [min p25 p50 p75 p90 p99 max] = {_quantiles(values)}")
    print(f"  exponent histogram (floor log10|v| -> count) = {_exponent_hist(values)}")
    for uc_label, uc in (("abstain (no unit)", None), ("declared unit C=1.0", 1.0)):
        adj = measure_unit_consistency(values, uc)
        r = adj.result
        post = dict(zip(("consistent", "mixed"), r.posterior, strict=True)) if r.posterior else {}
        wits = {w.witness_id: round(w.distribution[1], 3) for w in adj.witnesses}  # P(mixed) each
        print(
            f"  [{uc_label:>20}]  C={r.conflict:.4f}  U={r.ignorance:.4f}  "
            f"posterior(mixed)={post.get('mixed', float('nan')):.3f}  witnessP(mixed)={wits}"
        )


def main() -> None:
    emap_path = DATA / "detection-unit-v1" / "entropy_map.yaml"
    print("--- injection parameters (from entropy_map.yaml) ---")
    for line in emap_path.read_text().splitlines():
        s = line.strip()
        if s.startswith(("scale_factor", "mix_ratio", "target_column", "seed", "target_file")):
            print(f"  {s}")
    for table in ("invoices", "bank_transactions"):
        print(f"\n================= {table}.amount =================")
        clean = read_amount("clean", table)
        injected = read_amount("detection-unit-v1", table)
        report("CLEAN", clean)
        report("SCALE-MIXED (injected)", injected)


if __name__ == "__main__":
    main()
