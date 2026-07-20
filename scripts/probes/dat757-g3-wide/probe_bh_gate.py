"""DAT-757 /ground gate #1 — permutation p-values + BH-FDR replace the RFI magic constant.

CLAIM UNDER TEST (to refute)
----------------------------
"Replacing the mixed gate's `RFI > 0.05` significance arm with a permutation p-value
(P_perm(FI_null >= FI_obs), the variance-honest version of RFI's mean-centering) +
Benjamini–Hochberg FDR (q<=0.05) over the view's effect-screened candidate family
dominates the fixed threshold: it closes the E-grid leaks (3/40 skew x heavy-tail FPs,
where RFI's mean-centering ignores null VARIANCE), keeps every matrix/card-sweep true,
and abstains better at small n — without new magic constants (q=0.05 is a standard,
0.01 row-g3 stays as the effect-size semantics)."

Named methods: permutation test (exact, add-one corrected); Benjamini–Hochberg (1995).
Family choice (named, deliberate): FDR is controlled over the EFFECT-SCREENED candidate
set (pairs passing row-g3<=0.01 + guards / pair-count alias screen) — the hypotheses the
discovery procedure actually emits. The screen is part of discovery, the FDR controls
what gets ASSERTED from it. The chi-square/G-test analytic null is deliberately NOT used:
our contingency tables are extremely sparse (expected counts << 5 at mid/high card), the
regime where the asymptotic breaks — permutation is the honest null here.

THE ATTACK
----------
1) The 3 E-grid cells that leaked through RFI (the acceptance test) + the full grid.
2) The 32 structural matrix cells (must not lose the 32/32).
3) The card-sweep trues incl. card 0.85 x 3 seeds (RFI's thinnest margin, 0.063).
4) Small-n replicate war: n=200, effect-passing independent (extreme-skew dep) vs true
   FD, 20 replicates — count false asserts/misses, BH vs RFI.

Kill: any section where BH is worse than RFI, or no section where it is better.

Run:  uv run python scripts/probes/dat757-g3-wide/probe_bh_gate.py   (repo root, ~6 min)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from fdlib import (  # noqa: E402
    FD_MAX_G3,
    MIN_DISTINCT_DETERMINANT,
    MIN_DISTINCT_DIMENSION,
    NEAR_KEY_FRAC,
    Scan,
    alias_decision,
    bh_reject,
    edge_decision,
    perm_pvalue,
    rfi_of,
    scan_pairs,
)
from probe_matrix import CELLS, N, build_fact_a, build_fact_b  # noqa: E402

Q_FDR = 0.05


# --------------------------------------------------------------------------- #
# the BH gate: effect screen -> permutation p per candidate -> BH per family   #
# --------------------------------------------------------------------------- #
def edge_screen(scan: Scan, a: str, b: str) -> bool:
    """Effect + guards, identical to the mixed gate's edge arm minus significance."""
    key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
    ps = scan.stats[key]
    d_a, d_b = (ps.d_a, ps.d_b) if fwd else (ps.d_b, ps.d_a)
    g3 = ps.g3_row_fwd if fwd else ps.g3_row_bwd
    return (
        g3 <= FD_MAX_G3
        and d_a > d_b
        and d_a >= MIN_DISTINCT_DETERMINANT
        and not (scan.n and d_a >= NEAR_KEY_FRAC * scan.n)
        and d_b >= MIN_DISTINCT_DIMENSION
    )


def alias_screen(scan: Scan, a: str, b: str) -> bool:
    """Pair-count alias screen, identical to the mixed gate's alias arm minus RFI."""
    key = (a, b) if (a, b) in scan.stats else (b, a)
    ps = scan.stats[key]
    if ps.d_a < MIN_DISTINCT_DIMENSION or ps.d_b < MIN_DISTINCT_DIMENSION:
        return False
    return ps.g3_eng_fwd <= FD_MAX_G3 and ps.g3_eng_bwd <= FD_MAX_G3


def bh_decisions(scan: Scan, edges: list[tuple[str, str]], aliases: list[tuple[str, str]]):
    """(asserted_edges, merged_aliases) under the BH gate over one view's candidates."""
    cand_e = [(a, b) for a, b in edges if edge_screen(scan, a, b)]
    cand_a = [(a, b) for a, b in aliases if alias_screen(scan, a, b)]
    pvals: dict[tuple[str, str, str], float] = {}
    for a, b in cand_e:
        pvals[("e", a, b)] = perm_pvalue(scan, a, b)
    for a, b in cand_a:
        # dependence must be significant in BOTH directions for a 1:1 claim
        pvals[("a", a, b)] = max(perm_pvalue(scan, a, b), perm_pvalue(scan, b, a))
    rejected = bh_reject(pvals, m_family=max(1, len(pvals)), q=Q_FDR)
    return (
        {(a, b) for k, a, b in rejected if k == "e"},
        {(a, b) for k, a, b in rejected if k == "a"},
    )


def main() -> None:
    rng = np.random.default_rng(757_3)
    n = N

    # ---- 1: the E-grid acceptance test ----
    print("## 1 — E grid under BH (the 3 RFI leaks are the acceptance test)")
    shapes = ["0.10/uni", "0.30/uni", "0.30/heavy3", "0.65/heavy10", "0.85/heavy10"]

    def make_det(shape: str) -> np.ndarray:
        card, tail = shape.split("/")
        c = float(card)
        if tail == "uni":
            return rng.permutation(np.arange(n) % int(c * n))
        n_bulk = 10 if tail == "heavy10" else 3
        det = np.arange(n)
        frac = 1.0 - c + n_bulk / n
        idx = rng.choice(n, int(frac * n), replace=False)
        det[idx] = -rng.integers(1, n_bulk + 1, len(idx))
        return det

    fp_bh = fn_bh = fp_rfi = fn_rfi = cells = 0
    for p_min in (0.05, 0.01, 0.005, 0.001):
        for dep_k in (2, 5):
            u = rng.random(n)
            dep = np.where(u < p_min, 1 + rng.integers(0, dep_k - 1, n), 0)
            cols = {f"det{i}": make_det(s) for i, s in enumerate(shapes)}
            true_det = rng.permutation(np.arange(n) % 600)
            cols |= {"true_det": true_det, "dep": dep,
                     "true_dep": np.where(true_det < 600 * p_min, 1, 0)}
            scan = scan_pairs(pl.DataFrame(cols), list(cols))
            edge_cands = [(f"det{i}", "dep") for i in range(len(shapes))]
            edge_cands.append(("true_det", "true_dep"))
            asserted, _ = bh_decisions(scan, edge_cands, [])
            for i, s in enumerate(shapes):
                cells += 1
                if (f"det{i}", "dep") in asserted:
                    fp_bh += 1
                    print(f"    BH FP: {s} -> dep(k={dep_k}, min={p_min:.1%})")
                if edge_decision(scan, f"det{i}", "dep", "mixed"):
                    fp_rfi += 1
            if ("true_det", "true_dep") not in asserted:
                fn_bh += 1
                print(f"    BH FN: true control lost at k={dep_k}, min={p_min:.1%}")
            if not edge_decision(scan, "true_det", "true_dep", "mixed"):
                fn_rfi += 1
    print(f"  {cells} independent cells: BH FP {fp_bh}  (RFI/mixed FP {fp_rfi})")
    print(f"  8 true controls:          BH FN {fn_bh}  (RFI/mixed FN {fn_rfi})")

    # ---- 2: matrix structural cells ----
    print("\n## 2 — the 32 structural matrix cells under BH")
    rng_m = np.random.default_rng(20260714)
    df_a, df_b = build_fact_a(rng_m), build_fact_b(rng_m)
    scans = {"a": scan_pairs(df_a, df_a.columns), "b": scan_pairs(df_b, df_b.columns)}
    structural = [c for c in CELLS if c.lane == "structural"]
    per_scan_edges: dict[str, list] = {"a": [], "b": []}
    per_scan_alias: dict[str, list] = {"a": [], "b": []}
    for c in structural:
        (per_scan_edges if c.kind == "edge" else per_scan_alias)[c.fact].append((c.a, c.b))
    decided = {
        f: bh_decisions(scans[f], per_scan_edges[f], per_scan_alias[f]) for f in ("a", "b")
    }
    ok = 0
    for c in structural:
        asserted, merged = decided[c.fact]
        got = (c.a, c.b) in (asserted if c.kind == "edge" else merged)
        good = got == c.expect
        ok += good
        if not good:
            print(f"    BH misses cell {c.id}: want {c.expect}, got {got}")
    print(f"  BH: {ok}/32 structural cells  (mixed: 32/32)")

    # ---- 3: card-sweep trues + the 0.85 stability test ----
    print("\n## 3 — true-FD card sweep (dep 24): BH keeps all? + card-0.85 x 3 seeds")
    for c in (0.3, 0.5, 0.7, 0.8, 0.85):
        k = int(c * n)
        det = rng.permutation(np.arange(n) % k)
        dep = det * 24 // k
        scan = scan_pairs(pl.DataFrame({"det": det, "dep": dep}), ["det", "dep"])
        a_e, _ = bh_decisions(scan, [("det", "dep")], [])
        p = perm_pvalue(scan, "det", "dep")
        print(f"  card {c:.2f}: p={p:.2e}  BH {'KEEP' if ('det', 'dep') in a_e else 'LOSE'}")
    for seed in (1, 2, 3):
        r2 = np.random.default_rng(seed)
        k = int(0.85 * n)
        det = r2.permutation(np.arange(n) % k)
        dep = det * 24 // k
        scan = scan_pairs(pl.DataFrame({"det": det, "dep": dep}), ["det", "dep"])
        a_e, _ = bh_decisions(scan, [("det", "dep")], [])
        rfi = rfi_of(scan, "det", "dep")
        mixed_keeps = edge_decision(scan, "det", "dep", "mixed")
        print(f"  card 0.85 seed {seed}: RFI={rfi:.3f} (mixed {'keeps' if mixed_keeps else 'LOSES'})"
              f"  BH p={perm_pvalue(scan, 'det', 'dep'):.2e} "
              f"({'keeps' if ('det', 'dep') in a_e else 'LOSES'})")

    # ---- 4: small-n replicate war ----
    print("\n## 4 — n=200, 20 replicates: extreme-skew independent (effect-passing) vs true FD")
    n_small = 200
    bh_fp = rfi_fp = bh_fn = rfi_fn = screened = 0
    for rep in range(20):
        r3 = np.random.default_rng(1000 + rep)
        det = r3.permutation(np.arange(n_small) % 50)      # card 0.25 determinant
        dep_ind = np.zeros(n_small, dtype=np.int64)         # 99% dominant flag
        dep_ind[r3.choice(n_small, 2, replace=False)] = 1
        true_det = r3.permutation(np.arange(n_small) % 50)
        true_dep = true_det // 5                            # exact FD
        scan = scan_pairs(
            pl.DataFrame({"det": det, "dep_ind": dep_ind, "true_det": true_det, "true_dep": true_dep}),
            ["det", "dep_ind", "true_det", "true_dep"],
        )
        cands = [("det", "dep_ind"), ("true_det", "true_dep")]
        if edge_screen(scan, "det", "dep_ind"):
            screened += 1
        asserted, _ = bh_decisions(scan, cands, [])
        bh_fp += ("det", "dep_ind") in asserted
        bh_fn += ("true_det", "true_dep") not in asserted
        rfi_fp += edge_decision(scan, "det", "dep_ind", "mixed")
        rfi_fn += not edge_decision(scan, "true_det", "true_dep", "mixed")
    print(f"  independent (screen passed {screened}/20): BH FP {bh_fp}/20   RFI FP {rfi_fp}/20")
    print(f"  true FD:                                   BH FN {bh_fn}/20   RFI FN {rfi_fn}/20")

    print("\n## VERDICT: BUILD if BH >= mixed everywhere and > somewhere; else CUT.")


if __name__ == "__main__":
    main()
