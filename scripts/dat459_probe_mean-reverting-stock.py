"""DAT-459 PROBE — lens: mean-reverting / bounded stock.

ATTACK ON THE CLAIM: the reference spike (dat459_stock_flow_signature.py) builds its
"stock" as a PURE RANDOM WALK (cumsum of net movement) → rho1≈0.994, VR≈0.012. That is
the easy case. But not every stock is a random walk. A cash buffer, an inventory level,
a controlled/target-managed account is a genuine STOCK (a point-in-time level/balance),
yet it MEAN-REVERTS: it is AR(1) with phi<1. Its rho1 sits below 1 and could fall INTO
the FLOW band — making the signature MISS a real stock (false-negative).

We therefore synthesize honest stocks that are NOT random walks:
  - AR(1) levels  y_t = mu + phi*(y_{t-1}-mu) + eps,  phi in {0.95,0.8,0.6,0.4}
  - a bounded random walk with reflection at 0 (inventory can't go negative)
at the SAME small T as the fixture (T=12), many seeds, and measure rho1 & VR.

We compare against the REAL fixture flow band (the empirical rho1/VR of the actual
TB_net / TB_debit / GL_debit flows from load_series — the things DAT-445 must NOT
misclassify as stock). The verdict question: at what phi does a genuine AR(1) stock
become indistinguishable from a flow (rho1 inside the flow band / VR inside flow band),
and do any REAL fixture accounts' constructed running balances mean-revert into that
overlap? If yes → the {stock,flow} dichotomy is not well-posed; it is a spectrum and
the signature has a false-negative region.

NO TUNING: thresholds are derived from the fixture flow distribution itself (its max
rho1 / min VR = the natural boundary a non-tuned classifier would have to respect),
not chosen to make AR(1) pass or fail.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

# import the reference helpers verbatim (same series construction + stats + AUC)
_REF = Path(__file__).with_name("dat459_stock_flow_signature.py")
_spec = importlib.util.spec_from_file_location("dat459_ref", _REF)
_ref = importlib.util.module_from_spec(_spec)
import sys as _sys

_sys.argv = ["dat459_ref", "data/clean", "6"]  # ref reads DATA/MIN_T from argv at import
_spec.loader.exec_module(_ref)

rho1 = _ref.rho1
var_ratio = _ref.var_ratio
load_series = _ref.load_series
_auc = _ref._auc

RNG = np.random.default_rng(20260609)
T = 12  # the fixture's modal period count
N_SEEDS = 2000


# ── synthetic genuine STOCKS that are NOT random walks ────────────────────────

def ar1_level(phi: float, n: int, sigma: float = 1.0) -> np.ndarray:
    """A mean-reverting LEVEL (a stock). phi<1 => reverts to mu. This IS a stock."""
    y = np.empty(n)
    mu = 0.0
    # start near stationary distribution so it's a level, not a transient
    y[0] = mu + RNG.normal(0, sigma / np.sqrt(max(1e-6, 1 - phi * phi)))
    for t in range(1, n):
        y[t] = mu + phi * (y[t - 1] - mu) + RNG.normal(0, sigma)
    return y


def bounded_rw_reflect(n: int, sigma: float = 1.0, start: float = 50.0) -> np.ndarray:
    """Inventory-style stock: random walk reflected at 0 (can't go negative).
    A genuine stock (a level) but bounded => some mean-reversion at the floor."""
    y = np.empty(n)
    y[0] = start
    for t in range(1, n):
        step = RNG.normal(0, sigma)
        v = y[t - 1] + step
        if v < 0:
            v = -v  # reflect at zero
        y[t] = v
    return y


def main() -> None:
    # ── 1. establish the REAL fixture FLOW band (what must NOT read as stock) ──
    series = load_series()
    kept = {a: s for a, s in series.items() if len(s["TB_net"]) >= 6}
    flow_names = ["TB_net", "TB_debit", "GL_debit"]
    flow_rho = []
    flow_vr = []
    for a in kept:
        for fn in flow_names:
            r = rho1(kept[a][fn])
            v = var_ratio(kept[a][fn])
            if not np.isnan(r):
                flow_rho.append(r)
            if not np.isnan(v):
                flow_vr.append(v)
    flow_rho = np.array(flow_rho)
    flow_vr = np.array(flow_vr)

    # also the reference's own RW "stock" band, for contrast
    rw_stock_rho = np.array([rho1(kept[a]["STOCK_bal"]) for a in kept], dtype=float)
    rw_stock_vr = np.array([var_ratio(kept[a]["STOCK_bal"]) for a in kept], dtype=float)

    print(f"T={T}  N_SEEDS={N_SEEDS}  fixture flow samples={len(flow_rho)}")
    print()
    print("=== REAL fixture FLOW band (rho1, VR) — the no-go zone for a 'stock' verdict ===")
    print(f"  flow rho1:  median={np.median(flow_rho):+.3f}  "
          f"p95={np.percentile(flow_rho,95):+.3f}  max={flow_rho.max():+.3f}")
    print(f"  flow VR:    median={np.median(flow_vr):.3f}  "
          f"p05={np.percentile(flow_vr,5):.3f}  min={flow_vr.min():.3f}")
    print(f"  ref RW-stock rho1 median={np.median(rw_stock_rho):+.3f}  "
          f"VR median={np.median(rw_stock_vr):.3f}  (the EASY stock)")
    print()

    # A non-tuned classifier separating fixture RW-stock from fixture flow would place
    # its rho1 boundary somewhere between flow.max and RW-stock.min, and its VR boundary
    # between flow.min and RW-stock.max. Use the most GENEROUS-to-the-claim boundary:
    # the flow band's own extreme (anything beyond it => "stock"). That is the loosest
    # rule that still never misreads a fixture flow as a stock.
    rho_boundary = flow_rho.max()          # rho1 must EXCEED this to be called stock
    vr_boundary = flow_vr.min()            # VR must be BELOW this to be called stock
    print(f"[non-tuned boundary from fixture flows]  rho1>{rho_boundary:+.3f} => stock ;  "
          f"VR<{vr_boundary:.3f} => stock")
    print()

    # ── 2. synthetic mean-reverting STOCKS: do they clear the boundary? ────────
    print("=== synthetic GENUINE stocks (AR(1) levels + bounded RW) at T=12 ===")
    print(f"{'stock model':<22}{'rho1 med':>10}{'rho1 p05':>10}{'rho1 p95':>10}"
          f"{'VR med':>9}{'VR p95':>9}{'recall_rho':>12}{'recall_VR':>11}{'recall_OR':>11}")

    boundary_fail = {}
    for phi in (0.95, 0.8, 0.6, 0.4):
        rhos = np.array([rho1(ar1_level(phi, T)) for _ in range(N_SEEDS)])
        vrs = np.array([var_ratio(ar1_level(phi, T)) for _ in range(N_SEEDS)])
        rhos = rhos[~np.isnan(rhos)]
        vrs = vrs[~np.isnan(vrs)]
        rec_rho = np.mean(rhos > rho_boundary)        # fraction correctly called stock by rho1
        rec_vr = np.mean(vrs < vr_boundary)           # by VR
        # OR rule (called stock if EITHER fires) — most generous to the claim
        # recompute paired so OR is honest: regenerate paired samples
        paired_rho = []
        paired_vr = []
        for _ in range(N_SEEDS):
            y = ar1_level(phi, T)
            paired_rho.append(rho1(y))
            paired_vr.append(var_ratio(y))
        paired_rho = np.array(paired_rho)
        paired_vr = np.array(paired_vr)
        m = ~(np.isnan(paired_rho) | np.isnan(paired_vr))
        rec_or = np.mean((paired_rho[m] > rho_boundary) | (paired_vr[m] < vr_boundary))
        boundary_fail[f"AR1 phi={phi}"] = (rec_rho, rec_vr, rec_or)
        print(f"{'AR(1) phi='+str(phi):<22}{np.median(rhos):>10.3f}"
              f"{np.percentile(rhos,5):>10.3f}{np.percentile(rhos,95):>10.3f}"
              f"{np.median(vrs):>9.3f}{np.percentile(vrs,95):>9.3f}"
              f"{rec_rho:>12.2%}{rec_vr:>11.2%}{rec_or:>11.2%}")

    # bounded RW (inventory)
    b_rho = np.array([rho1(bounded_rw_reflect(T)) for _ in range(N_SEEDS)])
    b_vr = np.array([var_ratio(bounded_rw_reflect(T)) for _ in range(N_SEEDS)])
    pr, pv = [], []
    for _ in range(N_SEEDS):
        y = bounded_rw_reflect(T)
        pr.append(rho1(y)); pv.append(var_ratio(y))
    pr = np.array(pr); pv = np.array(pv)
    m = ~(np.isnan(pr) | np.isnan(pv))
    b_rec_rho = np.nanmean(b_rho > rho_boundary)
    b_rec_vr = np.nanmean(b_vr < vr_boundary)
    b_rec_or = np.mean((pr[m] > rho_boundary) | (pv[m] < vr_boundary))
    boundary_fail["bounded RW (reflect@0)"] = (b_rec_rho, b_rec_vr, b_rec_or)
    print(f"{'bounded RW reflect@0':<22}{np.nanmedian(b_rho):>10.3f}"
          f"{np.nanpercentile(b_rho,5):>10.3f}{np.nanpercentile(b_rho,95):>10.3f}"
          f"{np.nanmedian(b_vr):>9.3f}{np.nanpercentile(b_vr,95):>9.3f}"
          f"{b_rec_rho:>12.2%}{b_rec_vr:>11.2%}{b_rec_or:>11.2%}")
    print()
    print("  recall_X = fraction of these GENUINE stocks the signature correctly calls"
          " 'stock'. LOW recall = false-negatives (real stock read as flow).")
    print()

    # ── 3. AUC: AR(1) stock vs fixture flow (does ANY rule separate them?) ─────
    print("=== AUC: synthetic AR(1) stock rho1 vs fixture flow rho1 (1.0 clean, .5 none) ===")
    for phi in (0.95, 0.8, 0.6, 0.4):
        s_rho = np.array([rho1(ar1_level(phi, T)) for _ in range(N_SEEDS)])
        s_vr = np.array([var_ratio(ar1_level(phi, T)) for _ in range(N_SEEDS)])
        auc_rho = _auc(s_rho, flow_rho)               # P(stock_rho > flow_rho)
        auc_vr = _auc(flow_vr, s_vr)                  # P(flow_VR > stock_VR) -> stock lower
        print(f"  phi={phi}:  AUC_rho(stock>flow)={auc_rho:.3f}   "
              f"AUC_VR(flow>stock)={auc_vr:.3f}")
    print()

    # ── 4. do REAL fixture accounts' running balances mean-revert? ─────────────
    # The constructed STOCK_bal is cumsum (pure RW by construction). The real question:
    # are there real accounts whose LEVEL series (the running balance) is NOT a clean RW
    # — i.e. rho1 in a mid band rather than ~1? Inspect the spread of STOCK_bal rho1.
    print("=== REAL fixture constructed running-balance (STOCK_bal) rho1 spread ===")
    sr = rw_stock_rho[~np.isnan(rw_stock_rho)]
    print(f"  n={len(sr)}  min={sr.min():+.3f}  p10={np.percentile(sr,10):+.3f}  "
          f"median={np.median(sr):+.3f}  max={sr.max():+.3f}")
    n_midband = int(np.sum(sr < rho_boundary))
    print(f"  accounts whose running-balance rho1 falls AT/BELOW the flow boundary "
          f"({rho_boundary:+.3f}) => would be MISSED as stock: {n_midband}/{len(sr)}")
    print()

    # ── verdict summary ──
    print("=== FALSE-NEGATIVE BOUNDARY SUMMARY ===")
    for model, (rr, rv, ro) in boundary_fail.items():
        verdict = "MISSED (false-neg)" if ro < 0.5 else ("partial" if ro < 0.9 else "caught")
        print(f"  {model:<24} OR-rule recall={ro:6.2%}  -> {verdict}")


if __name__ == "__main__":
    main()
