"""DAT-459 PROBE — lens: redundancy-threshold.

Attack the claim that rho1 and VR are TWO independent witnesses cleanly separating
stock from flow with a stable, well-margined threshold. Specifically:

  (a) REDUNDANCY: for AR-shaped series VR ≈ 2(1-rho1). If rho1 and VR are
      ~deterministically related across the pooled account series, then claiming
      "two independent witnesses" in a DAT-445 pooling would be FALSE redundancy
      (double-counting one signal).

  (b) THRESHOLD: find the single best cut on rho1 (and on VR) separating flow from
      stock across the 27 accounts. Report misclassification count and MARGIN
      (gap between the worst stock and worst flow at that cut).

  (c) STABILITY: is the threshold in a crowded region (many points near it) or a
      wide empty gap? Report nearest flow / nearest stock distances to the cut.

  (d) HONEST POOLING: given (a), would pooling rho1+VR as two witnesses be honest,
      or should DAT-445 treat them as ONE witness?

Reuses series construction + stat fns from dat459_stock_flow_signature.py.
We pool ALL account series (each flow series of the 3 flow families + the stock)
into a labelled set, then run the redundancy + threshold analysis.

No tuning: thresholds are chosen by an exhaustive midpoint search to MINIMIZE
misclassification; we report whatever margin that yields.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dat459_stock_flow_signature import load_series, rho1, var_ratio  # noqa: E402

MIN_T = 6


def best_threshold(values: np.ndarray, labels: np.ndarray, stock_high: bool):
    """Exhaustive midpoint threshold minimizing misclassification.

    labels: 1 = stock, 0 = flow.
    stock_high: True if stock is expected on the HIGH side of the cut (rho1),
                False if stock is on the LOW side (VR).
    Returns (thr, n_misclass, margin, predict_fn).
    margin = (min over the side that should be stock) - (max over flow side)
             i.e. the signed gap; positive => clean linear separation.
    """
    mask = ~np.isnan(values)
    v = values[mask]
    y = labels[mask]
    order = np.unique(v)
    cands = (order[:-1] + order[1:]) / 2.0 if len(order) > 1 else order
    best = None
    for thr in cands:
        if stock_high:
            pred = (v >= thr).astype(int)
        else:
            pred = (v < thr).astype(int)  # stock on low side
        n_mis = int(np.sum(pred != y))
        if best is None or n_mis < best[1]:
            best = (float(thr), n_mis)
    thr, n_mis = best
    # margin: separability gap regardless of where thr sits
    stock_vals = v[y == 1]
    flow_vals = v[y == 0]
    if stock_high:
        margin = float(np.min(stock_vals) - np.max(flow_vals))
    else:
        margin = float(np.min(flow_vals) - np.max(stock_vals))
    return thr, n_mis, margin, stock_vals, flow_vals


def main() -> None:
    series_by_acct = load_series()
    kept = {a: s for a, s in series_by_acct.items() if len(s["TB_net"]) >= MIN_T}
    print(f"accounts kept (T>={MIN_T}) = {len(kept)}")

    flow_series_names = ["TB_debit", "TB_net", "GL_debit"]
    stock_name = "STOCK_bal"

    # Build pooled labelled point set: each (account, series) -> (rho1, VR, label)
    rho_vals, vr_vals, labels, tags = [], [], [], []
    for a, s in kept.items():
        for fname in flow_series_names:
            rho_vals.append(rho1(s[fname]))
            vr_vals.append(var_ratio(s[fname]))
            labels.append(0)
            tags.append(f"{a}:{fname}")
        rho_vals.append(rho1(s[stock_name]))
        vr_vals.append(var_ratio(s[stock_name]))
        labels.append(1)
        tags.append(f"{a}:{stock_name}")

    rho_vals = np.array(rho_vals, float)
    vr_vals = np.array(vr_vals, float)
    labels = np.array(labels, int)

    valid = ~np.isnan(rho_vals) & ~np.isnan(vr_vals)
    print(
        f"pooled points: total={len(labels)} valid(both stats)={int(valid.sum())} "
        f"stock={int(np.sum(labels[valid] == 1))} flow={int(np.sum(labels[valid] == 0))}"
    )
    print()

    rv = rho_vals[valid]
    vv = vr_vals[valid]
    lv = labels[valid]

    # ── (a) REDUNDANCY ────────────────────────────────────────────────────────
    print("=== (a) REDUNDANCY: is VR just a transform of rho1? ===")
    pear = float(np.corrcoef(rv, vv)[0, 1])
    # Spearman rank correlation (monotone-relationship strength)
    rr = np.argsort(np.argsort(rv))
    vrk = np.argsort(np.argsort(vv))
    spear = float(np.corrcoef(rr, vrk)[0, 1])
    print(f"Pearson(rho1, VR)  = {pear:+.4f}")
    print(f"Spearman(rho1, VR) = {spear:+.4f}")
    # Test the textbook AR identity VR = 2(1-rho1): residual of VR vs that prediction
    vr_pred = 2.0 * (1.0 - rv)
    resid = vv - vr_pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((vv - np.mean(vv)) ** 2))
    r2_identity = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    print(f"VR ≈ 2(1-rho1) identity:  R^2 of VR explained by 2(1-rho1) = {r2_identity:+.4f}")
    print(f"  mean|VR - 2(1-rho1)| = {np.mean(np.abs(resid)):.4f}  "
          f"median = {np.median(np.abs(resid)):.4f}")
    print()

    # ── (b) BEST SINGLE THRESHOLD on rho1 and on VR ─────────────────────────────
    print("=== (b) BEST SINGLE THRESHOLD (exhaustive, minimize misclass) ===")
    thr_r, mis_r, margin_r, stock_r, flow_r = best_threshold(rv, lv, stock_high=True)
    thr_v, mis_v, margin_v, stock_v, flow_v = best_threshold(vv, lv, stock_high=False)
    n_pts = len(lv)
    print(f"rho1:  thr={thr_r:+.4f}  misclass={mis_r}/{n_pts}  "
          f"linear-margin(min_stock - max_flow)={margin_r:+.4f}")
    print(f"  rho1  stock: min={np.min(stock_r):+.4f} median={np.median(stock_r):+.4f} "
          f"max={np.max(stock_r):+.4f}")
    print(f"  rho1  flow : min={np.min(flow_r):+.4f} median={np.median(flow_r):+.4f} "
          f"max={np.max(flow_r):+.4f}")
    print(f"VR:    thr={thr_v:+.4f}  misclass={mis_v}/{n_pts}  "
          f"linear-margin(min_flow - max_stock)={margin_v:+.4f}")
    print(f"  VR    stock: min={np.min(stock_v):+.4f} median={np.median(stock_v):+.4f} "
          f"max={np.max(stock_v):+.4f}")
    print(f"  VR    flow : min={np.min(flow_v):+.4f} median={np.median(flow_v):+.4f} "
          f"max={np.max(flow_v):+.4f}")
    print()

    # ── (c) STABILITY: crowded region? distance of nearest points to the cut ────
    print("=== (c) THRESHOLD STABILITY (nearest points to the chosen cut) ===")
    def crowd(values, thr, lab, name):
        nearest_flow = np.min(np.abs(values[lab == 0] - thr))
        nearest_stock = np.min(np.abs(values[lab == 1] - thr))
        # how many points within the margin band [thr +/- band]
        band = abs(margin_r if name == "rho1" else margin_v)
        within = int(np.sum(np.abs(values - thr) <= band)) if band > 0 else 0
        spread = float(np.max(values) - np.min(values))
        print(f"  {name}: nearest_flow_dist={nearest_flow:.4f} "
              f"nearest_stock_dist={nearest_stock:.4f} "
              f"empty-gap-width={nearest_flow + nearest_stock:.4f} "
              f"(as frac of full range {spread:.3f}: "
              f"{(nearest_flow + nearest_stock)/spread:.3f})")
        print(f"       points within +/-margin of cut: {within}/{len(values)}")
    crowd(rv, thr_r, lv, "rho1")
    crowd(vv, thr_v, lv, "VR")
    print()

    # ── (d) HONEST POOLING: do the two witnesses ever disagree? ─────────────────
    print("=== (d) HONEST POOLING: do rho1 and VR ever DISAGREE per point? ===")
    pred_r = (rv >= thr_r).astype(int)  # 1=stock by rho1
    pred_v = (vv < thr_v).astype(int)   # 1=stock by VR
    agree = int(np.sum(pred_r == pred_v))
    disagree = int(np.sum(pred_r != pred_v))
    print(f"  rho1-vote == VR-vote on {agree}/{n_pts} points; disagree on {disagree}")
    # Where they err, do they err on the SAME points (correlated errors => 1 witness)?
    err_r = pred_r != lv
    err_v = pred_v != lv
    both_err = int(np.sum(err_r & err_v))
    either_err = int(np.sum(err_r | err_v))
    print(f"  rho1 errors={int(err_r.sum())} VR errors={int(err_v.sum())} "
          f"both-wrong-same-point={both_err} either-wrong={either_err}")
    if either_err > 0:
        print(f"  error overlap (both/either) = {both_err}/{either_err} = "
              f"{both_err/either_err:.2f}  (->1.0 = errors fully redundant = ONE witness)")
    else:
        print("  no errors by either single witness")
    print()

    # ── VERDICT NUMBERS summary ─────────────────────────────────────────────────
    print("=== VERDICT NUMBERS ===")
    print(f"redundancy |Pearson(rho1,VR)|={abs(pear):.3f} Spearman={abs(spear):.3f} "
          f"identity-R^2={r2_identity:.3f}")
    print(f"rho1 cut={thr_r:+.3f} misclass={mis_r}/{n_pts} margin={margin_r:+.4f}")
    print(f"VR   cut={thr_v:+.3f} misclass={mis_v}/{n_pts} margin={margin_v:+.4f}")


if __name__ == "__main__":
    main()


def overlap_detail() -> None:
    """Identify the overlapping points near the rho1 cut (the inverted pair)."""
    series_by_acct = load_series()
    kept = {a: s for a, s in series_by_acct.items() if len(s["TB_net"]) >= MIN_T}
    flow_series_names = ["TB_debit", "TB_net", "GL_debit"]
    rows = []
    for a, s in kept.items():
        for fname in flow_series_names:
            rows.append((rho1(s[fname]), var_ratio(s[fname]), 0, f"{a}:{fname}"))
        rows.append((rho1(s["STOCK_bal"]), var_ratio(s["STOCK_bal"]), 1, f"{a}:STOCK_bal"))
    rows = [r for r in rows if not (np.isnan(r[0]) or np.isnan(r[1]))]
    rows.sort(key=lambda r: r[0])
    print("\n=== OVERLAP DETAIL: points sorted by rho1, near the boundary [0.55, 0.72] ===")
    for rho, vr, lab, tag in rows:
        if 0.50 <= rho <= 0.72:
            kind = "STOCK" if lab == 1 else "flow"
            print(f"  rho1={rho:+.4f}  VR={vr:+.4f}  {kind:<5}  {tag}")


if __name__ == "__main__":
    main()
    overlap_detail()
