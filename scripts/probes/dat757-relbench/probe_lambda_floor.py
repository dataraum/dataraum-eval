"""DAT-757 RelBench fold — the skew-floor gate: Goodman–Kruskal lambda >= 0.5.

CLAIM UNDER TEST (pre-registered, ONE attempt)
----------------------------------------------
rel-salt exposed the vacuous-skew class: dependents with >=99% majority share make
row-g3 <= 0.01 satisfiable by ANY determinant (g3 == minority mass, zero reduction
over the majority baseline), and neither perm-p+BH (real weak dependence IS
significant at n=200k) nor RFI (H(dep) tiny => FI inflated) blocks it — measured:
BH 151 / mixed(RFI) 147 extras on rel-salt.

The named statistic: Goodman–Kruskal lambda (1954), the PRE measure
    lambda(a->b) = 1 - g3_row(a->b) / minority_mass(b)
(reduction in prediction error over always-predicting b's majority). Exact FDs get
lambda = 1 regardless of skew, so true edges onto skewed flags survive. Floor
pre-registered at lambda >= 0.5 ("explains at least half the baseline error" —
the PRE midpoint, chosen before running).

Predictions (stated before the run): salt's ~40 vacuous ->DISTRIBUTIONCHANNEL /
->SALESOFFICE extras die (lambda ~= 0); real org edges survive (SOLDTO->SALESOFFICE
lambda ~= 0.66); hm's dirty-true hierarchy edges survive (lambda ~= 0.8); f1
untouched; ZERO exact-truth edges lost on any leg. Kill: any truth edge blocked,
or the vacuous class survives.

Evaluated on the effect-screened candidate set (BH accepted 71/71, 81/81, 191/192
of it — the screen IS the decision surface here). Aliases are bijections; the
floor applies to the edge arm only.

Run:  uv run python -u scripts/probes/dat757-relbench/probe_lambda_floor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parents[1] / "dat757-g3-wide"))
sys.path.insert(0, str(Path(__file__).parent))

from fdlib import MIN_DISTINCT_DIMENSION, scan_pairs  # noqa: E402
from probe_bh_gate import edge_screen  # noqa: E402
from probe_fold_grade import SPECS, build_obt, truth_tables  # noqa: E402

LAMBDA_MIN = 0.5


def main() -> None:
    for name in ("rel-f1", "rel-hm", "rel-salt"):
        print(f"\n# {name}")
        obt, group = build_obt(Path("corpora/relbench") / name, SPECS[name])
        cols = list(obt.columns)
        scan = scan_pairs(obt, cols)
        truth_e, _ = truth_tables(scan, cols)
        eligible = [c for c in cols if scan.singles[c] >= MIN_DISTINCT_DIMENSION]
        n = len(obt)
        minority = {
            c: 1.0
            - obt.get_column(c).cast(pl.Utf8).fill_null("␀").value_counts()["count"].max() / n
            for c in eligible
        }

        def lam(a: str, b: str) -> float:
            key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
            g3 = scan.stats[key].g3_row_fwd if fwd else scan.stats[key].g3_row_bwd
            return 1.0 - g3 / minority[b] if minority[b] > 0 else 0.0

        t_kept = t_lost = x_kept = x_lost = 0
        lost_truth, kept_extras = [], []
        for i, a in enumerate(eligible):
            for b in eligible[i + 1 :]:
                for s, t in ((a, b), (b, a)):
                    if not edge_screen(scan, s, t):
                        continue
                    ok = lam(s, t) >= LAMBDA_MIN
                    if (s, t) in truth_e:
                        t_kept += ok
                        t_lost += not ok
                        if not ok:
                            lost_truth.append((s, t))
                    else:
                        x_kept += ok
                        x_lost += not ok
                        if ok:
                            kept_extras.append((s, t, lam(s, t)))
        print(f"  truth edges screened:  kept {t_kept}  BLOCKED {t_lost}")
        for s, t in lost_truth:
            print(f"    LOST TRUTH: {s} -> {t}  (lambda {lam(s, t):.3f})")
        print(f"  extra edges screened:  kept {x_kept}  blocked {x_lost}")
        for s, t, lv in sorted(kept_extras, key=lambda x: -x[2])[:12]:
            print(f"    surviving extra: {s} -> {t}  lambda {lv:.2f} [{group[s]}->{group[t]}]")


if __name__ == "__main__":
    main()
