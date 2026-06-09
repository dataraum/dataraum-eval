"""DAT-459 PROBE — lens: trending/seasonal FLOW false-positive.

CLAIM UNDER TEST (to refute): rho1 (lag-1 autocorr of the level) and VR=Var(Δy)/Var(y)
CLEANLY separate STOCK (rho1->1, VR->0) from FLOW (rho1->0, VR->~2) at T~12, no tuning.
Quoted bands: stock rho1 ~0.994 vs flow ~0.04/-0.135; stock VR ~0.012 vs flow ~1.77-2.0.
A clean threshold gap is claimed (e.g. rho1=0.5 splits them).

THE ATTACK: a FLOW that trends or is seasonal has POSITIVE autocorrelation and LOW VR.
Revenue ramping each quarter, growing expenses, a q4_seasonal_boost=0.3 (which IS in
this fixture's generator) — these are flows whose *level* drifts smoothly, so consecutive
periods are correlated. If a trending/seasonal flow's rho1 crosses into the STOCK band
(rho1>0.5) / its VR drops near the stock VR, that is a FALSE POSITIVE: DAT-445 would claim
a flow column is a stock. The most dangerous error in a balance-sheet/P&L classifier.

Three legs:
  (a) REAL: measure rho1/VR on the actual flow series (TB_net, TB_debit, GL_debit) for
      revenue & expense accounts specifically (the seasonally/growth-shaped ones), and
      report the upper tail of the whole flow class.
  (b) SYNTHETIC worst case at T=12: linear ramp+noise, exponential growth+noise, strong
      12-month seasonal sine+noise, ramp+seasonal combos, low-noise variants. Do any land
      in the stock band rho1>0.5? What's the max rho1 / min VR reachable by a *flow*?
  (c) GAP: flow-class rho1 p90/p95/max vs the stock band lower edge. Is there still a clean
      threshold, or do the distributions overlap?

We reuse load_series / rho1 / var_ratio / _auc from the spike script verbatim (no tuning).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dat459_stock_flow_signature import (  # noqa: E402
    _auc,
    load_series,
    rho1,
    var_ratio,
)

DATA = Path("data/clean")
MIN_T = 6
STOCK_RHO_BAND = 0.5  # the claimed splitting threshold: rho1>0.5 => "stock"
RNG = np.random.default_rng(459)


def _quantiles(arr: np.ndarray, label: str) -> str:
    a = arr[~np.isnan(arr)]
    if len(a) == 0:
        return f"{label}: (all-nan)"
    return (
        f"{label}: n={len(a)} min={np.min(a):+.3f} p50={np.median(a):+.3f} "
        f"p90={np.quantile(a, 0.90):+.3f} p95={np.quantile(a, 0.95):+.3f} max={np.max(a):+.3f}"
    )


def leg_a_real_flows() -> dict:
    """rho1/VR on the REAL flow series, focused on revenue/expense (drift/seasonal) accounts."""
    series = load_series()
    coa = pd.read_csv(DATA / "chart_of_accounts.csv", dtype={"account_id": str})
    acct_type = dict(zip(coa["account_id"], coa["account_type"].str.lower()))

    kept = {a: s for a, s in series.items() if len(s["TB_net"]) >= MIN_T}
    Ts = [len(s["TB_net"]) for s in kept.values()]
    print(f"[a] accounts kept (T>={MIN_T}) = {len(kept)}  T: min={min(Ts)} med={int(np.median(Ts))} max={max(Ts)}")

    flow_names = ["TB_net", "TB_debit", "GL_debit"]
    pl_types = {"revenue", "expense"}

    out = {}
    # ALL flows + the P&L subset (the trending/seasonal-prone class)
    for subset_label, predicate in [
        ("ALL-accounts", lambda a: True),
        ("P&L(rev+exp)", lambda a: acct_type.get(a, "") in pl_types),
    ]:
        accts = [a for a in kept if predicate(a)]
        all_rho, all_vr = [], []
        for fname in flow_names:
            rhos = np.array([rho1(kept[a][fname]) for a in accts], dtype=float)
            vrs = np.array([var_ratio(kept[a][fname]) for a in accts], dtype=float)
            all_rho.append(rhos)
            all_vr.append(vrs)
        all_rho = np.concatenate(all_rho)
        all_vr = np.concatenate(all_vr)
        print(f"\n[a] {subset_label}  (flows={flow_names}, n_accts={len(accts)})")
        print("    " + _quantiles(all_rho, "rho1"))
        print("    " + _quantiles(all_vr, "VR  "))
        n_cross = int(np.sum(all_rho[~np.isnan(all_rho)] > STOCK_RHO_BAND))
        n_tot = int(np.sum(~np.isnan(all_rho)))
        print(f"    flows with rho1 > {STOCK_RHO_BAND} (would be MISCLASSIFIED as stock): {n_cross}/{n_tot}")
        out[subset_label] = {"rho": all_rho, "vr": all_vr, "n_cross": n_cross, "n_tot": n_tot}

    # per-type breakdown of the worst (max) rho1 — which flow type drifts most?
    print("\n[a] per-account-type worst-case flow rho1 (TB_net):")
    for t in ["revenue", "expense", "asset", "liability", "equity"]:
        accts = [a for a in kept if acct_type.get(a, "") == t]
        if not accts:
            continue
        rhos = np.array([rho1(kept[a]["TB_net"]) for a in accts], dtype=float)
        rhos = rhos[~np.isnan(rhos)]
        if len(rhos):
            print(f"    {t:<10} n={len(rhos):>2}  max_rho1={np.max(rhos):+.3f}  med={np.median(rhos):+.3f}  "
                  f"#>{STOCK_RHO_BAND}={int(np.sum(rhos > STOCK_RHO_BAND))}")
    return out


def _make_stock_reference(T: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Honest stock = running balance = cumsum of net flow (matches spike construction)."""
    rhos, vrs = [], []
    for _ in range(n):
        net = RNG.normal(0, 1, T)  # per-period net movement
        y = np.cumsum(net)  # running balance == stock
        rhos.append(rho1(y))
        vrs.append(var_ratio(y))
    return np.array(rhos), np.array(vrs)


def leg_b_synthetic_worst_case(T: int = 12, n: int = 4000) -> dict:
    """Synthesize trending/seasonal FLOWS and ask: do they invade the stock band?"""
    print(f"\n[b] synthetic worst-case FLOWS at T={T}, n={n} each. "
          f"A FLOW is per-period movement; we make it TREND/SEASONAL (still a flow).")

    t = np.arange(T)
    families: dict[str, np.ndarray] = {}

    def collect(name: str, gen):
        rhos = np.empty(n)
        vrs = np.empty(n)
        for i in range(n):
            y = gen()
            rhos[i] = rho1(y)
            vrs[i] = var_ratio(y)
        families[name] = np.column_stack([rhos, vrs])

    # noise scaled so signal-to-noise spans realistic-to-adversarial (low noise = worst case)
    # linear ramp flow: y_t = slope*t + noise  (e.g. growing monthly revenue)
    for snr in (0.05, 0.15, 0.5):
        collect(f"linear_ramp(noise={snr})",
                lambda snr=snr: t * 1.0 + RNG.normal(0, snr * T, T))
    # exponential growth flow: y_t = (1+g)^t + noise (compounding expense/revenue)
    for snr in (0.05, 0.15):
        collect(f"exp_growth(noise={snr})",
                lambda snr=snr: np.power(1.25, t) + RNG.normal(0, snr * np.power(1.25, t).std(), T))
    # strong 12-month seasonal sine flow: one full cycle over T=12 + noise
    for snr in (0.05, 0.2):
        collect(f"seasonal_sine(noise={snr})",
                lambda snr=snr: np.sin(2 * np.pi * t / 12.0) + RNG.normal(0, snr, T))
    # q4_seasonal_boost shape: flat then a Q4 bump (the actual generator pattern) + noise
    def q4boost():
        base = RNG.normal(10, 1.0, T)
        q4 = (t % 12) >= 9  # last 3 months of a year
        base[q4] *= 1.3
        return base
    collect("q4_boost(generator-like)", q4boost)
    # ramp + seasonal combo (revenue that grows AND has Q4 spike)
    for snr in (0.05, 0.2):
        collect(f"ramp+seasonal(noise={snr})",
                lambda snr=snr: t * 1.0 + 3.0 * np.sin(2 * np.pi * t / 12.0) + RNG.normal(0, snr * T, T))
    # smooth random-walk-ish FLOW via heavy AR(1) on the flow itself (autocorrelated movement,
    # NOT cumulative) — flows can be serially correlated without being stocks.
    for phi in (0.7, 0.9):
        def ar1(phi=phi):
            y = np.empty(T)
            y[0] = RNG.normal()
            for k in range(1, T):
                y[k] = phi * y[k - 1] + RNG.normal(0, 1)
            return y
        collect(f"AR1_flow(phi={phi})", ar1)

    # stock reference distribution (for the gap/AUC)
    stock_rho, stock_vr = _make_stock_reference(T, n)
    print(f"    [ref] STOCK rho1: med={np.nanmedian(stock_rho):+.3f} "
          f"p05={np.nanquantile(stock_rho, 0.05):+.3f} p50={np.nanmedian(stock_rho):+.3f}")
    print(f"    [ref] STOCK VR  : med={np.nanmedian(stock_vr):+.3f} "
          f"p95={np.nanquantile(stock_vr, 0.95):+.3f}")

    print(f"\n[b] per-family FLOW signature (does it invade stock band rho1>{STOCK_RHO_BAND}?):")
    worst_rho = -np.inf
    worst_fam = None
    all_flow_rho = []
    all_flow_vr = []
    for name, rv in families.items():
        rhos, vrs = rv[:, 0], rv[:, 1]
        rhos_v = rhos[~np.isnan(rhos)]
        vrs_v = vrs[~np.isnan(vrs)]
        all_flow_rho.append(rhos_v)
        all_flow_vr.append(vrs_v)
        frac_cross = float(np.mean(rhos_v > STOCK_RHO_BAND)) if len(rhos_v) else np.nan
        # AUC: P(stock_rho > flow_rho). 1.0 = clean (stock always higher). <1 = overlap.
        auc_rho = _auc(stock_rho, rhos)
        auc_vr = _auc(stock_vr, vrs)  # stock VR should be LOWER => want this near 0
        mx = np.max(rhos_v) if len(rhos_v) else np.nan
        if len(rhos_v) and mx > worst_rho:
            worst_rho, worst_fam = mx, name
        print(f"    {name:<28} rho1 med={np.median(rhos_v):+.3f} p95={np.quantile(rhos_v,0.95):+.3f} "
              f"max={mx:+.3f} | VR med={np.median(vrs_v):.3f} min={np.min(vrs_v):.3f} | "
              f"%rho>{STOCK_RHO_BAND}={frac_cross:.2%} | AUC_rho={auc_rho:.3f} AUC_vr={auc_vr:.3f}")

    all_flow_rho = np.concatenate(all_flow_rho)
    all_flow_vr = np.concatenate(all_flow_vr)
    print(f"\n[b] WORST single flow family by max rho1: {worst_fam}  max_rho1={worst_rho:+.3f}")
    return {
        "flow_rho": all_flow_rho,
        "flow_vr": all_flow_vr,
        "stock_rho": stock_rho,
        "stock_vr": stock_vr,
        "families": families,
        "worst_rho": worst_rho,
        "worst_fam": worst_fam,
    }


def leg_c_gap(real: dict, synth: dict) -> dict:
    """Is there a clean threshold gap between the flow class (incl. trending) and the stock band?"""
    print("\n[c] OVERLAP / THRESHOLD-GAP analysis")
    # Combine real flows + synthetic trending flows into the FLOW class.
    real_flow_rho = np.concatenate([real["ALL-accounts"]["rho"], real["P&L(rev+exp)"]["rho"]])
    flow_rho = np.concatenate([real_flow_rho[~np.isnan(real_flow_rho)], synth["flow_rho"]])
    stock_rho = synth["stock_rho"][~np.isnan(synth["stock_rho"])]

    flow_p95 = np.quantile(flow_rho, 0.95)
    flow_p99 = np.quantile(flow_rho, 0.99)
    flow_max = np.max(flow_rho)
    stock_p05 = np.quantile(stock_rho, 0.05)
    stock_p01 = np.quantile(stock_rho, 0.01)
    stock_min = np.min(stock_rho)

    print(f"    FLOW class rho1 (real+synthetic trending): "
          f"p95={flow_p95:+.3f} p99={flow_p99:+.3f} max={flow_max:+.3f}")
    print(f"    STOCK band rho1:                            "
          f"p05={stock_p05:+.3f} p01={stock_p01:+.3f} min={stock_min:+.3f}")
    gap_p95_p05 = stock_p05 - flow_p95
    gap_max_min = stock_min - flow_max
    print(f"    GAP (stock_p05 - flow_p95) = {gap_p95_p05:+.3f}   "
          f"(positive => separable at those quantiles)")
    print(f"    GAP (stock_min - flow_max) = {gap_max_min:+.3f}   "
          f"(positive => NO overlap at all; negative => bands OVERLAP)")

    # overall AUC stock-vs-(all flows incl. trending)
    auc = _auc(stock_rho, flow_rho)
    print(f"    AUC P(stock_rho > flow_rho) over full flow class = {auc:.3f}  "
          f"(1.0 clean; lower => trending flows eat into stock band)")

    # what % of trending flows would be misread as stock at threshold 0.5?
    frac_flow_above = float(np.mean(flow_rho > STOCK_RHO_BAND))
    frac_stock_below = float(np.mean(stock_rho < STOCK_RHO_BAND))
    print(f"    @threshold rho1>{STOCK_RHO_BAND}: "
          f"FALSE-POSITIVE (flow read as stock) rate = {frac_flow_above:.2%}; "
          f"FALSE-NEGATIVE (stock read as flow) rate = {frac_stock_below:.2%}")
    return {
        "gap_max_min": gap_max_min,
        "gap_p95_p05": gap_p95_p05,
        "auc": auc,
        "fp_rate": frac_flow_above,
        "flow_max": flow_max,
        "stock_min": stock_min,
    }


def main() -> None:
    print("=" * 78)
    print("DAT-459 PROBE — trending/seasonal FLOW false-positive attack on rho1/VR separator")
    print("=" * 78)
    real = leg_a_real_flows()
    synth = leg_b_synthetic_worst_case(T=12, n=4000)
    gap = leg_c_gap(real, synth)

    print("\n" + "=" * 78)
    print("VERDICT INPUTS")
    print("=" * 78)
    print(f"  real P&L flows misclassified as stock: "
          f"{real['P&L(rev+exp)']['n_cross']}/{real['P&L(rev+exp)']['n_tot']}")
    print(f"  worst synthetic trending flow max rho1 = {synth['worst_rho']:+.3f} ({synth['worst_fam']})")
    print(f"  full flow-class rho1 max = {gap['flow_max']:+.3f}  vs  stock band min = {gap['stock_min']:+.3f}")
    print(f"  band overlap gap (stock_min - flow_max) = {gap['gap_max_min']:+.3f}")
    print(f"  AUC(stock>flow) over full flow class = {gap['auc']:.3f}")
    print(f"  false-positive rate @rho1>0.5 = {gap['fp_rate']:.2%}")


if __name__ == "__main__":
    main()
