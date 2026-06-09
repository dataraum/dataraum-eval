"""DAT-459 redirect — STRUCTURAL reconciliation stock/flow discriminator (ms-level grounding).

The time-series persistence signature (rho1/VR) was FALSIFIED (scripts/dat459_probe_*.py): it conflates
smoothness with level-vs-movement, so trending flows false-fire as stock and mean-reverting stocks
false-fire as flow. The redirect: discriminate STRUCTURALLY against the INDEPENDENT per-period movements
(from journal_lines), not from the column's own shape.

Discriminator. For a period-keyed column y[1..T] (per account) and the independent per-period net movement
m[1..T] (GL net for that account+period, computed from journal_lines — NOT from y):
  FLOW hypothesis : y[t] ≈ m[t]              (the column IS the period's movement)
  STOCK hypothesis: Δy[t] ≈ m[t]   (t>=2)    (the column CARRIES FORWARD: change == period movement)
Scale-free residuals (no tuning, no boost curve):
  R_flow  = Σ|y[t]      − m[t]|   / Σ|m[t]|        over t=1..T
  R_stock = Σ|Δy[t]     − m[t]|   / Σ|m[t]|        over t=2..T
Classify STOCK iff R_stock < R_flow. Margin = (R_flow − R_stock) (sign = direction, |·| = confidence).

Why this is robust where rho1 failed (the whole point):
  - a TRENDING/seasonal flow still equals its per-period movement → R_flow≈0, R_stock large → FLOW. ✓
  - a MEAN-REVERTING stock still carries forward (Δlevel == net movement regardless of reversion)
    → R_stock≈0, R_flow large → STOCK. ✓
Both are the cases that broke the persistence statistic.

We grade it the SAME adversarial way: real fixture + the rho1-killer synthetics, each WITH realistic
reconciliation NOISE (the column won't equal its anchor exactly — rounding, timing, missing txns,
restatements). We sweep the noise and report the break point. If it ALSO walls, we say so.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data/clean")
RNG = np.random.default_rng(20260609)  # fixed; varies cases by construction, not Math.random


def _period_key(p: str) -> tuple[int, int]:
    y, m = p.split("-")
    return int(y), int(m)


def load_fixture() -> dict[str, dict]:
    """Per account: the candidate series + the INDEPENDENT GL net-movement anchor."""
    tb = pd.read_csv(DATA / "trial_balance.csv", dtype={"account_id": str})
    jl = pd.read_csv(DATA / "journal_lines.csv", dtype={"account_id": str, "entry_id": str})
    je = pd.read_csv(DATA / "journal_entries.csv", dtype={"entry_id": str})
    je["date"] = pd.to_datetime(je["date"])
    je["period"] = je["date"].dt.strftime("%Y-%m")
    if "status" in je.columns:
        je = je[je["status"].astype(str).str.lower() == "posted"]
    jlp = jl.merge(je[["entry_id", "period"]], on="entry_id", how="inner")
    gl = (
        jlp.groupby(["account_id", "period"], as_index=False)
        .agg(gl_debit=("debit", "sum"), gl_credit=("credit", "sum"))
    )
    gl["gl_net"] = gl["gl_debit"] - gl["gl_credit"]

    out: dict[str, dict] = {}
    for acct, g in tb.groupby("account_id"):
        g = g.sort_values("period", key=lambda s: s.map(_period_key))
        periods = list(g["period"])
        tb_net = (g["debit_balance"] - g["credit_balance"]).to_numpy(float)
        gacct = gl[gl["account_id"] == acct].set_index("period")
        m_net = np.array([float(gacct["gl_net"].get(p, 0.0)) for p in periods])  # INDEPENDENT anchor
        if len(m_net) < 4 or np.sum(np.abs(m_net)) == 0:
            continue
        out[acct] = {
            "periods": periods,
            "m_net": m_net,                       # independent per-period net movement (the anchor)
            "FLOW_tb_net": tb_net,                # real flow column (== m_net up to rounding)
            "STOCK_running": np.cumsum(m_net),    # the would-be materialized stock (carry-forward level)
        }
    return out


# ── the structural discriminator ─────────────────────────────────────────────

def reconcile(y: np.ndarray, m: np.ndarray) -> tuple[float, float, str]:
    """Return (R_flow, R_stock, label). label in {'stock','flow'}."""
    denom = np.sum(np.abs(m)) or 1.0
    r_flow = float(np.sum(np.abs(y - m)) / denom)
    dy = np.diff(y)
    r_stock = float(np.sum(np.abs(dy - m[1:])) / (np.sum(np.abs(m[1:])) or 1.0))
    return r_flow, r_stock, ("stock" if r_stock < r_flow else "flow")


def add_recon_noise(y: np.ndarray, m: np.ndarray, frac: float) -> np.ndarray:
    """Perturb the column away from a perfect reconciliation by `frac` of the movement scale."""
    if frac <= 0:
        return y
    scale = np.median(np.abs(m[m != 0])) if np.any(m != 0) else 1.0
    return y + RNG.normal(0, frac * scale, size=len(y))


# ── synthetic adversarial cases (the rho1-killers), each with its own anchor ──

def synth_cases(T: int = 12, n: int = 400) -> dict[str, list[tuple[np.ndarray, np.ndarray, str]]]:
    """Each case -> list of (y, m_anchor, true_label)."""
    cases: dict[str, list] = {}

    def flow_anchor(y):  # a flow's period movement IS the value
        return y.copy()

    def stock_from_movements(m):  # a stock is the running total of its movements
        return np.cumsum(m)

    # trending / seasonal FLOWS (broke rho1 -> read as stock). truth = flow.
    cases["trend_flow"] = []
    cases["season_flow"] = []
    cases["q4boost_flow"] = []
    # mean-reverting / bounded STOCKS (broke rho1 -> read as flow). truth = stock.
    cases["ar1_0.6_stock"] = []
    cases["ar1_0.4_stock"] = []
    cases["sawtooth_stock"] = []  # quarterly-close stock (broke noisy-stock probe)

    for i in range(n):
        base = 1e5 * (1 + 0.3 * i / n)
        noise = RNG.normal(0, 0.15 * base, T)
        # trending flow: linear ramp
        y = base + np.arange(T) * 0.15 * base + noise
        cases["trend_flow"].append((y, flow_anchor(y), "flow"))
        # seasonal flow
        y = base + 0.5 * base * np.sin(2 * np.pi * np.arange(T) / 12) + noise
        cases["season_flow"].append((y, flow_anchor(y), "flow"))
        # q4 boost flow (generator-like): months 9,10,11 boosted
        y = base + noise
        y[9:12] *= 1.3
        cases["q4boost_flow"].append((y, flow_anchor(y), "flow"))
        # AR(1) mean-reverting STOCK: y_t = phi*y_{t-1}+eps; movement = Δy
        for phi, key in ((0.6, "ar1_0.6_stock"), (0.4, "ar1_0.4_stock")):
            lvl = np.zeros(T)
            lvl[0] = base
            for t in range(1, T):
                lvl[t] = base * (1 - phi) + phi * lvl[t - 1] + RNG.normal(0, 0.1 * base)
            cases[key].append((lvl, np.concatenate([[lvl[0]], np.diff(lvl)]), "stock"))
        # sawtooth STOCK: accumulates then closes to ~0 every quarter; carry-forward still holds.
        m = RNG.normal(0.1 * base, 0.05 * base, T)
        lvl = stock_from_movements(m)
        for q in range(2, T, 3):  # close: a big negative movement zeroing the level
            close = -lvl[q]
            m[q] += close
            lvl = stock_from_movements(m)
        cases["sawtooth_stock"].append((lvl, m, "stock"))
    return cases


def _summ(labels_true, labels_pred, margins):
    correct = np.mean([t == p for t, p in zip(labels_true, labels_pred)])
    mm = np.array(margins)
    return correct, np.median(mm), np.percentile(mm, 5), np.percentile(mm, 95)


def main() -> None:
    fx = load_fixture()
    print(f"DATA={DATA}  accounts={len(fx)}  (T>=4, non-zero movement)")
    print()

    # ── REAL fixture: flow column + constructed stock, vs independent GL anchor ──
    print("=== REAL fixture (reconciled against INDEPENDENT journal_lines net movement) ===")
    for col, truth in (("FLOW_tb_net", "flow"), ("STOCK_running", "stock")):
        rf, rs, preds, margins = [], [], [], []
        for a, d in fx.items():
            r_flow, r_stock, label = reconcile(d[col], d["m_net"])
            rf.append(r_flow); rs.append(r_stock); preds.append(label)
            margins.append(r_flow - r_stock if truth == "stock" else r_stock - r_flow)
        acc = np.mean([p == truth for p in preds])
        print(f"  {col:<14} truth={truth:<5} acc={acc:5.1%}  "
              f"R_flow med={np.median(rf):.3f}  R_stock med={np.median(rs):.3f}  "
              f"correct-margin med={np.median(margins):+.3f} p5={np.percentile(margins,5):+.3f}")
    print("  (FLOW_tb_net should reconcile as flow ~R_flow≈0; STOCK_running as stock ~R_stock≈0)")
    print()

    # ── ADVERSARIAL synthetics (the rho1-killers) at zero recon-noise ──
    print("=== ADVERSARIAL synthetics @ zero reconciliation-noise (the rho1-killers) ===")
    cases = synth_cases()
    for name, items in cases.items():
        truths = [t for _, _, t in items]
        preds, margins = [], []
        for y, m, truth in items:
            r_flow, r_stock, label = reconcile(y, m)
            preds.append(label)
            margins.append((r_flow - r_stock) if truth == "stock" else (r_stock - r_flow))
        acc, mmed, m5, m95 = _summ(truths, preds, margins)
        flag = "OK " if acc >= 0.95 else "BREAK"
        print(f"  [{flag}] {name:<16} truth={truths[0]:<5} acc={acc:5.1%}  correct-margin med={mmed:+.3f} p5={m5:+.3f}")
    print()

    # ── ROBUSTNESS: sweep reconciliation noise on the adversarial cases ──
    print("=== ROBUSTNESS: accuracy vs reconciliation-noise (column ≠ anchor exactly) ===")
    print(f"  {'case':<16}" + "".join(f"{('n='+str(f)):>9}" for f in [0.0, 0.05, 0.1, 0.25, 0.5, 1.0]))
    for name, items in cases.items():
        row = f"  {name:<16}"
        for frac in [0.0, 0.05, 0.1, 0.25, 0.5, 1.0]:
            preds, truths = [], []
            for y, m, truth in items:
                yn = add_recon_noise(y, m, frac)
                _, _, label = reconcile(yn, m)
                preds.append(label); truths.append(truth)
            acc = np.mean([p == t for p, t in zip(preds, truths)])
            row += f"{acc:>9.0%}"
        print(row)
    print("  (break = where flow and stock residuals cross; bounds how exact a real reconciliation must be)")
    print()

    # ── WRONG-ANCHOR: does the witness ABSTAIN (small margin) rather than confidently misclassify? ──
    print("=== WRONG-ANCHOR guardrail (reconcile against a corrupted/misaligned anchor) ===")
    accts = list(fx.values())
    for col in ("FLOW_tb_net", "STOCK_running"):
        # correct anchor
        good = [abs(reconcile(d[col], d["m_net"])[0] - reconcile(d[col], d["m_net"])[1]) for d in accts]
        # shuffled anchor (movements from the wrong account / wrong order)
        shuf = []
        for i, d in enumerate(accts):
            wrong = accts[(i + 1) % len(accts)]["m_net"]
            n = min(len(wrong), len(d[col]))
            shuf.append(abs(reconcile(d[col][:n], wrong[:n])[0] - reconcile(d[col][:n], wrong[:n])[1]))
        # both-large detector: with a wrong anchor, BOTH residuals are large -> low confidence
        both_large = []
        for i, d in enumerate(accts):
            wrong = accts[(i + 1) % len(accts)]["m_net"]
            n = min(len(wrong), len(d[col]))
            rf, rs, _ = reconcile(d[col][:n], wrong[:n])
            both_large.append(min(rf, rs))  # if min residual is large, neither hypothesis fits -> abstain
        print(f"  {col:<14} |margin| correct med={np.median(good):.3f}  "
              f"wrong-anchor med={np.median(shuf):.3f}  "
              f"wrong-anchor min-residual med={np.median(both_large):.3f}")
    print("  (guardrail: with the wrong anchor, min(R_flow,R_stock) stays LARGE -> abstain rule = "
          "'fire only when the winning residual is near 0'; a mis-aligned anchor never reconciles to ~0)")


if __name__ == "__main__":
    main()
