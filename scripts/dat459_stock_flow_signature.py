"""DAT-459 — stock/flow temporal-signature SPIKE (ms-level, real fixtures).

Ground-the-statistic-FIRST (the unit_consistency/bimodality lesson): before building
the DAT-445 temporal_behavior measurement, find which statistic — if any — cleanly
separates a STOCK (point-in-time level / running balance) from a FLOW (per-period
movement) on the real month-end-close corpus, at the small period counts that fixture
actually has. If none separates → report it as a wall, don't force it.

KEY GROUNDING FINDING this script verifies first: the testdata `trial_balance` is
PER-PERIOD ACTIVITY, not cumulative (generators._derive_trial_balance docstring +
line 945). So `trial_balance.debit_balance` is itself a FLOW (the per-period GL
aggregate), NOT a stock. The fixture materializes NO true stock column. We therefore
*construct* the honest latent stock — the running net balance, cumsum of per-period
net movement per account — and test whether any statistic separates it from the flows.

Series built per account (sorted by period):
  TB_debit   = trial_balance.debit_balance               (flow, gross)
  TB_net     = debit_balance - credit_balance            (flow, net)
  GL_debit   = sum(journal_lines.debit) per period       (flow; should ~match TB_debit)
  STOCK_bal  = cumsum(TB_net)                             (synthetic stock = running balance)

Candidate statistics (small-N robust where possible), per series y[1..T]:
  rho1        lag-1 autocorrelation of the level   (stock→~1, flow→~0)
  var_ratio   Var(Δy)/Var(y)                       (flow→~2, random-walk stock→small)
  adf_gamma   coef of y_{t-1} in Δy~y_{t-1}        (flow mean-reverts→strong neg; stock→~0)
  adf_p       ADF p-value (if T big enough)        (flow→small/stationary, stock→large)
  frac_up     fraction of Δy>0                     (drifting stock→far from .5; flow→~.5)
  last_over_sum |y[-1]|/Σ|y|                        (monotone cumsum→~1; flow→~1/T)

Separation is PAIRED across accounts (each account yields s on its own flow series and
its own stock series): report what fraction of accounts have s(stock) separated from
s(flow), the medians, and a rank AUC. AUC≈1/0 = clean separator; AUC≈.5 = no signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data/clean")
MIN_T = int(sys.argv[2]) if len(sys.argv) > 2 else 6  # min periods to keep an account


def _period_key(p: str) -> tuple[int, int]:
    y, m = p.split("-")
    return int(y), int(m)


def load_series() -> dict[str, dict[str, np.ndarray]]:
    """Return {account_id: {series_name: values-over-periods}}."""
    tb = pd.read_csv(DATA / "trial_balance.csv", dtype={"account_id": str})
    jl = pd.read_csv(DATA / "journal_lines.csv", dtype={"account_id": str, "entry_id": str})
    je = pd.read_csv(DATA / "journal_entries.csv", dtype={"entry_id": str})

    # GL per (account, period): join lines->entries for the date, posted only.
    je["date"] = pd.to_datetime(je["date"])
    je["period"] = je["date"].dt.strftime("%Y-%m")
    status_col = "status" if "status" in je.columns else None
    if status_col:
        posted = je[je[status_col].astype(str).str.lower() == "posted"][["entry_id", "period"]]
    else:
        posted = je[["entry_id", "period"]]
    jlp = jl.merge(posted, on="entry_id", how="inner")
    gl = (
        jlp.groupby(["account_id", "period"], as_index=False)[["debit", "credit"]]
        .sum()
        .rename(columns={"debit": "gl_debit", "credit": "gl_credit"})
    )

    out: dict[str, dict[str, np.ndarray]] = {}
    for acct, g in tb.groupby("account_id"):
        g = g.copy()
        g = g.sort_values("period", key=lambda s: s.map(_period_key))
        tb_debit = g["debit_balance"].to_numpy(dtype=float)
        tb_credit = g["credit_balance"].to_numpy(dtype=float)
        tb_net = tb_debit - tb_credit
        stock = np.cumsum(tb_net)  # running net balance = the honest latent stock
        series = {
            "TB_debit": tb_debit,
            "TB_net": tb_net,
            "STOCK_bal": stock,
        }
        # GL debit per period for this account, aligned to TB periods
        gacct = gl[gl["account_id"] == acct].set_index("period")
        gl_debit = np.array([gacct["gl_debit"].get(p, 0.0) for p in g["period"]], dtype=float)
        series["GL_debit"] = gl_debit
        out[acct] = series
    return out


# ── candidate statistics ────────────────────────────────────────────────────

def rho1(y: np.ndarray) -> float:
    if len(y) < 3 or np.std(y) == 0:
        return np.nan
    y0, y1 = y[:-1], y[1:]
    s0, s1 = np.std(y0), np.std(y1)
    if s0 == 0 or s1 == 0:
        return np.nan
    return float(np.corrcoef(y0, y1)[0, 1])


def var_ratio(y: np.ndarray) -> float:
    if len(y) < 3 or np.var(y) == 0:
        return np.nan
    return float(np.var(np.diff(y)) / np.var(y))


def adf_stats(y: np.ndarray) -> tuple[float, float]:
    """Return (gamma coef on y_{t-1}, adf p-value). NaN if too short/degenerate."""
    if len(y) < 8 or np.std(y) == 0:
        return np.nan, np.nan
    try:
        res = adfuller(y, maxlag=1, regression="c", autolag=None)
        p = float(res[1])
    except Exception:
        p = np.nan
    # gamma via OLS of Δy on y_{t-1} (with intercept)
    dy = np.diff(y)
    ylag = y[:-1]
    X = np.column_stack([np.ones_like(ylag), ylag])
    try:
        beta, *_ = np.linalg.lstsq(X, dy, rcond=None)
        gamma = float(beta[1])
    except Exception:
        gamma = np.nan
    return gamma, p


def frac_up(y: np.ndarray) -> float:
    if len(y) < 3:
        return np.nan
    dy = np.diff(y)
    nz = dy[dy != 0]
    if len(nz) == 0:
        return np.nan
    return float(np.mean(nz > 0))


def last_over_sum(y: np.ndarray) -> float:
    s = np.sum(np.abs(y))
    if s == 0:
        return np.nan
    return float(np.abs(y[-1]) / s)


STATS = {
    "rho1": rho1,
    "var_ratio": var_ratio,
    "frac_up": frac_up,
    "last_over_sum": last_over_sum,
}


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Rank AUC: P(pos > neg). 1.0/0.0 clean, 0.5 no separation. NaN-safe."""
    pos = pos[~np.isnan(pos)]
    neg = neg[~np.isnan(neg)]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    wins = 0.0
    for a in pos:
        wins += np.sum(a > neg) + 0.5 * np.sum(a == neg)
    return float(wins / (len(pos) * len(neg)))


def main() -> None:
    series_by_acct = load_series()
    coa_path = DATA / "chart_of_accounts.csv"
    acct_type = {}
    if coa_path.exists():
        coa = pd.read_csv(coa_path, dtype={"account_id": str})
        type_col = "account_type" if "account_type" in coa.columns else None
        if type_col:
            acct_type = dict(zip(coa["account_id"], coa[type_col]))

    # keep accounts with enough periods
    kept = {a: s for a, s in series_by_acct.items() if len(s["TB_net"]) >= MIN_T}
    Ts = [len(s["TB_net"]) for s in series_by_acct.values()]
    print(f"DATA={DATA}  accounts={len(series_by_acct)}  kept(T>={MIN_T})={len(kept)}")
    print(f"period-count T per account: min={min(Ts)} median={int(np.median(Ts))} max={max(Ts)}")
    print()

    # sanity: does GL_debit match TB_debit (confirms TB == per-period GL aggregate)?
    diffs = []
    for s in kept.values():
        a, b = s["TB_debit"], s["GL_debit"]
        denom = np.sum(np.abs(a)) or 1.0
        diffs.append(np.sum(np.abs(a - b)) / denom)
    print(f"[grounding] mean |TB_debit - GL_debit| / |TB_debit| across accounts = {np.mean(diffs):.4f}")
    print("            (≈0 ⟹ trial_balance IS the per-period GL aggregate ⟹ TB is a FLOW, not a stock)")
    print()

    flow_series = ["TB_debit", "TB_net", "GL_debit"]
    stock_series = "STOCK_bal"

    # ── per-statistic medians + paired separation ────────────────────────────
    print("=== statistic distributions (median across accounts) ===")
    header = f"{'stat':<14}" + "".join(f"{n:>14}" for n in [*flow_series, stock_series])
    print(header)
    for sname, fn in STATS.items():
        vals = {}
        for series_name in [*flow_series, stock_series]:
            arr = np.array([fn(kept[a][series_name]) for a in kept], dtype=float)
            vals[series_name] = arr
        row = f"{sname:<14}" + "".join(
            f"{np.nanmedian(vals[n]):>14.3f}" for n in [*flow_series, stock_series]
        )
        print(row)
    print()

    print("=== PAIRED separation: STOCK_bal vs each flow (rank AUC; 1.0/0.0 clean, .5 none) ===")
    print(f"{'stat':<14}" + "".join(f"{('AUC vs '+n):>18}" for n in flow_series))
    for sname, fn in STATS.items():
        stock_vals = np.array([fn(kept[a][stock_series]) for a in kept], dtype=float)
        cells = ""
        for fseries in flow_series:
            flow_vals = np.array([fn(kept[a][fseries]) for a in kept], dtype=float)
            cells += f"{_auc(stock_vals, flow_vals):>18.3f}"
        print(f"{sname:<14}{cells}")
    print()

    # ADF (needs longer series) — report separately with coverage
    print("=== ADF (T>=8 only): gamma coef + p-value medians, and AUC ===")
    long_accts = [a for a in kept if len(kept[a]["TB_net"]) >= 8]
    print(f"accounts with T>=8: {len(long_accts)}")
    if long_accts:
        for series_name in [*flow_series, stock_series]:
            gammas, ps = [], []
            for a in long_accts:
                g, p = adf_stats(kept[a][series_name])
                gammas.append(g)
                ps.append(p)
            print(
                f"  {series_name:<12} gamma_med={np.nanmedian(gammas):+.4f}  "
                f"adf_p_med={np.nanmedian(ps):.3f}  "
                f"frac_stationary(p<.05)={np.nanmean(np.array(ps) < 0.05):.2f}"
            )
        # AUC on adf_p: stock should have HIGHER p (non-stationary)
        stock_p = np.array([adf_stats(kept[a][stock_series])[1] for a in long_accts], dtype=float)
        for fseries in flow_series:
            flow_p = np.array([adf_stats(kept[a][fseries])[1] for a in long_accts], dtype=float)
            print(f"  AUC adf_p STOCK>flow ({fseries}): {_auc(stock_p, flow_p):.3f}")
    print()

    # ── account_type cross-check (real accounting: P&L=flow, BS=stock) ────────
    if acct_type:
        print("=== account_type cross-check (does the MATERIALIZED TB column look like a flow for all?) ===")
        pl = {"revenue", "expense"}
        bs = {"asset", "liability", "equity"}
        for label, types in [("P&L (flow)", pl), ("BalanceSheet (stock?)", bs)]:
            accts = [a for a in kept if acct_type.get(a, "").lower() in types]
            if not accts:
                continue
            r1 = np.nanmedian([rho1(kept[a]["TB_net"]) for a in accts])
            fu = np.nanmedian([frac_up(kept[a]["TB_net"]) for a in accts])
            los = np.nanmedian([last_over_sum(kept[a]["TB_net"]) for a in accts])
            print(f"  {label:<22} n={len(accts):>3}  TB_net rho1={r1:+.3f} frac_up={fu:.3f} last/sum={los:.3f}")
        print("  (if BS and P&L TB_net look alike ⟹ the materialized column is flow-shaped regardless of account type)")


if __name__ == "__main__":
    main()
