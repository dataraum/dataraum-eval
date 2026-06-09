"""DAT-459 PROBE — lens: TAUTOLOGY.

Claim under attack: rho1->1 / VR->0 for STOCK and rho1->0 / VR->2 for FLOW
"CLEANLY and ROBUSTLY separate a stock from a flow" and is "a sound basis to
build temporal_behavior (claim {stock,flow} vs this signature witness)".

The tautology attack: cumsum of ANY non-degenerate sequence is autocorrelated.
So the signature might be detecting THE CUMSUM OPERATION, not a semantic
stock/flow property. If true, the witness can only ever say "this column was
produced by integrating something" — it cannot distinguish a *meaningful*
running balance from an integrated pile of noise, and it has zero power to tell
whether the SOURCE movements were a real flow or junk.

Tests (all reuse the spike's series construction + stat fns):
  (a) Permutation invariance: cumsum a RANDOM PERMUTATION of each account's
      TB_net. If rho1->1 regardless of order, the signature ignores the actual
      temporal content — it's the cumsum operation, not the data.
  (b) Integrated white noise: cumsum of i.i.d. Gaussian of matched length T.
      If rho1->1, "high rho1" == "this is a random walk", not "this is a real
      balance". This is the classic spurious-regression / unit-root fact.
  (c) Inverse honesty / collisions:
      - Can a genuine FLOW ever read as stock (rho1 high)? Scan all real flow
        series for rho1 >= the stock cutoff.
      - Can a genuine STOCK ever read as flow (rho1 low)? differenced stock
        (which is just the flow back again) — does it read flow? And does an
        already-trending real flow (revenue with growth) read as stock?
  (d) What the signature ACTUALLY separates: integrated-vs-not. Build a
      "junk stock" = cumsum(shuffle(flow)) and ask whether rho1/VR can tell the
      junk stock apart from the honest stock. If AUC~0.5, the signature has NO
      power to distinguish a meaningful running total from an arbitrary one ->
      it detects integration, not "stock".
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dat459_stock_flow_signature import (  # noqa: E402
    _auc,
    load_series,
    rho1,
    var_ratio,
)

RNG = np.random.default_rng(0xDA7459)
MIN_T = 6


def main() -> None:
    series_by_acct = load_series()
    kept = {a: s for a, s in series_by_acct.items() if len(s["TB_net"]) >= MIN_T}
    print(f"accounts kept (T>={MIN_T}) = {len(kept)}")
    Ts = [len(s["TB_net"]) for s in kept.values()]
    print(f"T per account: min={min(Ts)} median={int(np.median(Ts))} max={max(Ts)}\n")

    # baseline: real honest stock vs real flow (the claim's headline numbers)
    real_stock_rho = np.array([rho1(kept[a]["STOCK_bal"]) for a in kept])
    real_flow_rho = np.array([rho1(kept[a]["TB_net"]) for a in kept])
    real_stock_vr = np.array([var_ratio(kept[a]["STOCK_bal"]) for a in kept])
    real_flow_vr = np.array([var_ratio(kept[a]["TB_net"]) for a in kept])
    print("=== BASELINE (reproduce claim) ===")
    print(f"  honest STOCK rho1 median = {np.nanmedian(real_stock_rho):+.3f}")
    print(f"  real   FLOW  rho1 median = {np.nanmedian(real_flow_rho):+.3f}")
    print(f"  AUC rho1 stock>flow      = {_auc(real_stock_rho, real_flow_rho):.3f}")
    print(f"  honest STOCK VR median   = {np.nanmedian(real_stock_vr):.3f}")
    print(f"  real   FLOW  VR median   = {np.nanmedian(real_flow_vr):.3f}")
    print(f"  AUC VR stock>flow        = {_auc(real_stock_vr, real_flow_vr):.3f}\n")

    # ---- (a) permutation invariance --------------------------------------
    # cumsum of a SHUFFLED copy of the same flow values. Same multiset, scrambled
    # temporal order. If rho1 still ->1, the order (= the real temporal content)
    # is irrelevant; we only detect that we summed something.
    N_PERM = 200
    perm_stock_rho = []
    perm_stock_vr = []
    for a in kept:
        flow = kept[a]["TB_net"]
        rs, vs = [], []
        for _ in range(N_PERM):
            shuffled = RNG.permutation(flow)
            js = np.cumsum(shuffled)
            rs.append(rho1(js))
            vs.append(var_ratio(js))
        perm_stock_rho.append(np.nanmean(rs))
        perm_stock_vr.append(np.nanmean(vs))
    perm_stock_rho = np.array(perm_stock_rho)
    perm_stock_vr = np.array(perm_stock_vr)
    print("=== (a) PERMUTATION INVARIANCE: cumsum(shuffle(flow)) ===")
    print(f"  permuted-junk-stock rho1 median = {np.nanmedian(perm_stock_rho):+.3f}")
    print(f"  permuted-junk-stock VR   median = {np.nanmedian(perm_stock_vr):.3f}")
    print(f"  (vs honest stock rho1 {np.nanmedian(real_stock_rho):+.3f}, VR {np.nanmedian(real_stock_vr):.3f})")
    # Does junk stock STILL read as 'stock' under the claim's separation?
    # AUC junk-stock vs real-flow on rho1 (high = junk passes as stock too).
    print(f"  AUC rho1 junkStock>realFlow     = {_auc(perm_stock_rho, real_flow_rho):.3f}")
    print(f"  AUC VR   junkStock>realFlow     = {_auc(perm_stock_vr, real_flow_vr):.3f}  (low=junk reads stock-like)\n")

    # ---- (b) integrated white noise --------------------------------------
    # cumsum of i.i.d. N(0,1) at matched T. The classic unit-root fact: a random
    # walk has rho1 -> 1. If so, "high rho1" cannot mean "meaningful balance".
    iid_rho, iid_vr = [], []
    for a in kept:
        T = len(kept[a]["TB_net"])
        rs, vs = [], []
        for _ in range(N_PERM):
            rw = np.cumsum(RNG.standard_normal(T))
            rs.append(rho1(rw))
            vs.append(var_ratio(rw))
        iid_rho.append(np.nanmean(rs))
        iid_vr.append(np.nanmean(vs))
    iid_rho = np.array(iid_rho)
    iid_vr = np.array(iid_vr)
    print("=== (b) INTEGRATED WHITE NOISE: cumsum(iid Gaussian), matched T ===")
    print(f"  random-walk rho1 median = {np.nanmedian(iid_rho):+.3f}")
    print(f"  random-walk VR   median = {np.nanmedian(iid_vr):.3f}")
    print(f"  AUC rho1 randWalk>realFlow = {_auc(iid_rho, real_flow_rho):.3f}  (high=RW passes as stock)")
    print(f"  AUC VR   randWalk>realFlow = {_auc(iid_vr, real_flow_vr):.3f}  (low=RW reads stock-like)\n")

    # ---- (c) inverse honesty / collisions --------------------------------
    # cutoff = midpoint between the two real medians on rho1.
    cutoff = 0.5 * (np.nanmedian(real_stock_rho) + np.nanmedian(real_flow_rho))
    print(f"=== (c) INVERSE HONESTY (rho1 cutoff = {cutoff:+.3f}) ===")
    flow_names = ["TB_debit", "TB_net", "GL_debit"]
    n_flow_total = 0
    n_flow_as_stock = 0
    for fn_name in flow_names:
        vals = np.array([rho1(kept[a][fn_name]) for a in kept])
        vals = vals[~np.isnan(vals)]
        n_flow_total += len(vals)
        n_flow_as_stock += int(np.sum(vals >= cutoff))
        print(f"  FLOW {fn_name:<9} rho1>=cutoff: {int(np.sum(vals>=cutoff))}/{len(vals)} "
              f"(max={np.max(vals):+.3f})")
    print(f"  => real FLOW series misreading as STOCK: {n_flow_as_stock}/{n_flow_total}")

    # differenced stock == the flow again: does diff(stock) read as flow?
    diffstock_rho = np.array([rho1(np.diff(kept[a]["STOCK_bal"])) for a in kept])
    n_ds_stock = int(np.nansum(diffstock_rho >= cutoff))
    print(f"  diff(STOCK)=flow rho1 median = {np.nanmedian(diffstock_rho):+.3f}  "
          f"(reads-as-stock: {n_ds_stock}/{np.sum(~np.isnan(diffstock_rho))})\n")

    # ---- (d) the decisive test: can the signature tell HONEST stock from JUNK stock?
    # If a measurement claims to detect "stock", it must separate a meaningful
    # running balance from cumsum(noise) / cumsum(shuffle). Both are integrated.
    print("=== (d) DECISIVE: honest STOCK vs JUNK stock (both integrated) ===")
    print("  If AUC ~ 0.5, the signature has NO power to tell a real balance from")
    print("  an integrated arbitrary series -> it detects INTEGRATION, not 'stock'.")
    auc_rho_honest_vs_perm = _auc(real_stock_rho, perm_stock_rho)
    auc_rho_honest_vs_iid = _auc(real_stock_rho, iid_rho)
    auc_vr_honest_vs_perm = _auc(real_stock_vr, perm_stock_vr)
    auc_vr_honest_vs_iid = _auc(real_stock_vr, iid_vr)
    print(f"  AUC rho1 honestStock vs permJunkStock = {auc_rho_honest_vs_perm:.3f}")
    print(f"  AUC rho1 honestStock vs iidRandomWalk = {auc_rho_honest_vs_iid:.3f}")
    print(f"  AUC VR   honestStock vs permJunkStock = {auc_vr_honest_vs_perm:.3f}")
    print(f"  AUC VR   honestStock vs iidRandomWalk = {auc_vr_honest_vs_iid:.3f}")


if __name__ == "__main__":
    main()
