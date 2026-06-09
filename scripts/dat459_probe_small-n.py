"""DAT-459 PROBE — small-N robustness lens.

LENS: Small-N robustness — does the stock/flow separation survive T=4,6,8,10,12?

The ADR explicitly worries about "small/period-sparse data". The spike's headline
numbers (rho1 stock median 0.994, AUC 0.996-1.000) were measured at the fixture's
NATURAL T (~12). A real stock/flow column in the wild may have only 4-8 periods.

ATTACK: for T in {4,6,8,10,12}, TRUNCATE each account's series to the FIRST T periods,
recompute rho1 and var_ratio for each flow series vs the constructed-stock series, and
report:
  - the paired rank AUC at each T (STOCK vs each flow)
  - the within-class spread (std of the statistic across accounts) at each T
  - the min T at which AUC stays >= 0.9 (a usable separator)

Default-skeptic: if separation collapses below T=8, DAT-445 needs a minimum-period
guardrail (abstain when too few periods). We do NOT tune anything.

Reuses the EXACT series construction (load_series) and stat fns (rho1, var_ratio, _auc)
from scripts/dat459_stock_flow_signature.py — imported, not reimplemented.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse the reference spike's exact construction + statistics + AUC.
from dat459_stock_flow_signature import (  # noqa: E402
    _auc,
    load_series,
    rho1,
    var_ratio,
)

FLOW_SERIES = ["TB_debit", "TB_net", "GL_debit"]
STOCK_SERIES = "STOCK_bal"
T_GRID = [4, 6, 8, 10, 12]
STATS = {"rho1": rho1, "var_ratio": var_ratio}

# A "usable separator": for rho1 (stock > flow) AUC >= 0.9; for var_ratio (stock < flow)
# the separating AUC is the inverted one, so we track |AUC - 0.5| via max(auc, 1-auc).


def truncate(series: dict[str, np.ndarray], t: int) -> dict[str, np.ndarray]:
    """First-T-periods truncation. STOCK must be recomputed from the truncated FLOW
    (cumsum of the first T net movements), NOT sliced from the full-length cumsum —
    slicing the full cumsum would leak the running balance's later trajectory."""
    out = {}
    for name in FLOW_SERIES:
        out[name] = series[name][:t]
    # honest stock for the first T periods = cumsum of the first-T net movement.
    tb_net_t = series["TB_net"][:t]
    out[STOCK_SERIES] = np.cumsum(tb_net_t)
    return out


def main() -> None:
    series_by_acct = load_series()
    # Only accounts that actually HAVE >= max(T_GRID) periods, so every T uses the
    # SAME account set (clean paired comparison across T, no composition shift).
    full = {a: s for a, s in series_by_acct.items() if len(s["TB_net"]) >= max(T_GRID)}
    print(f"accounts total={len(series_by_acct)}  with T>={max(T_GRID)} kept={len(full)}")
    Ts = [len(s["TB_net"]) for s in series_by_acct.values()]
    print(f"natural T per account: min={min(Ts)} median={int(np.median(Ts))} max={max(Ts)}")
    print()

    # For each statistic: AUC and within-class spread at each T.
    for sname, fn in STATS.items():
        direction = "stock>flow" if sname == "rho1" else "stock<flow (separating=1-AUC)"
        print(f"=== {sname}  [{direction}] ===")
        hdr = f"{'T':>3} | " + " ".join(f"{('AUC '+f):>16}" for f in FLOW_SERIES)
        hdr += f" | {'std(stock)':>11} {'std(flowTBnet)':>15} {'med(stock)':>11} {'med(flowTBnet)':>15}"
        print(hdr)
        for t in T_GRID:
            trunc = {a: truncate(full[a], t) for a in full}
            stock_vals = np.array([fn(trunc[a][STOCK_SERIES]) for a in full], dtype=float)
            cells = ""
            for fseries in FLOW_SERIES:
                flow_vals = np.array([fn(trunc[a][fseries]) for a in full], dtype=float)
                cells += f"{_auc(stock_vals, flow_vals):>16.3f}"
            flow_tbnet = np.array([fn(trunc[a]["TB_net"]) for a in full], dtype=float)
            std_stock = np.nanstd(stock_vals)
            std_flow = np.nanstd(flow_tbnet)
            med_stock = np.nanmedian(stock_vals)
            med_flow = np.nanmedian(flow_tbnet)
            n_valid_stock = int(np.sum(~np.isnan(stock_vals)))
            n_valid_flow = int(np.sum(~np.isnan(flow_tbnet)))
            print(
                f"{t:>3} | {cells} | {std_stock:>11.3f} {std_flow:>15.3f} "
                f"{med_stock:>11.3f} {med_flow:>15.3f}  (valid stock={n_valid_stock} flow={n_valid_flow})"
            )
        print()

    # Min-T verdict: smallest T at which the SEPARATING AUC stays >= 0.9 for ALL flows.
    print("=== MIN-T at which separator stays usable (separating-AUC >= 0.9 for ALL 3 flows) ===")
    for sname, fn in STATS.items():
        usable_at = {}
        for t in T_GRID:
            trunc = {a: truncate(full[a], t) for a in full}
            stock_vals = np.array([fn(trunc[a][STOCK_SERIES]) for a in full], dtype=float)
            sep_aucs = []
            for fseries in FLOW_SERIES:
                flow_vals = np.array([fn(trunc[a][fseries]) for a in full], dtype=float)
                auc = _auc(stock_vals, flow_vals)
                # separating power = distance from 0.5 mapped to [0.5,1]
                sep = max(auc, 1.0 - auc) if not np.isnan(auc) else np.nan
                sep_aucs.append(sep)
            all_usable = all((not np.isnan(s)) and s >= 0.9 for s in sep_aucs)
            usable_at[t] = (all_usable, [round(s, 3) for s in sep_aucs])
        min_usable = next((t for t in T_GRID if usable_at[t][0]), None)
        print(f"  {sname:<10} usable(>=0.9 all flows): "
              + ", ".join(f"T={t}:{usable_at[t][0]}({usable_at[t][1]})" for t in T_GRID))
        print(f"             -> MIN usable T = {min_usable}")
    print()

    # Worst-case stress: also report the FRACTION of accounts where stock and flow
    # rho1 actually flip order at small T (the within-pair failure rate).
    print("=== within-pair failure rate (rho1): frac of accounts where stock rho1 <= flow rho1 ===")
    for t in T_GRID:
        trunc = {a: truncate(full[a], t) for a in full}
        fails = 0
        comparable = 0
        for a in full:
            sv = rho1(trunc[a][STOCK_SERIES])
            fv = rho1(trunc[a]["TB_net"])
            if np.isnan(sv) or np.isnan(fv):
                continue
            comparable += 1
            if sv <= fv:
                fails += 1
        rate = fails / comparable if comparable else float("nan")
        print(f"  T={t:>2}: fail={fails}/{comparable}  rate={rate:.3f}")


if __name__ == "__main__":
    main()


def diagnose_failures() -> None:
    """Identify which accounts flip at small T and how marginal the AUC really is."""
    series_by_acct = load_series()
    full = {a: s for a, s in series_by_acct.items() if len(s["TB_net"]) >= max(T_GRID)}
    coa_path = Path("data/clean/chart_of_accounts.csv")
    import pandas as pd
    atype = {}
    if coa_path.exists():
        coa = pd.read_csv(coa_path, dtype={"account_id": str})
        if "account_type" in coa.columns:
            atype = dict(zip(coa["account_id"], coa["account_type"]))
    print("\n=== DIAGNOSE: accounts where stock rho1 <= flow rho1 at T=4 ===")
    t = 4
    for a in full:
        tr = truncate(full[a], t)
        sv, fv = rho1(tr[STOCK_SERIES]), rho1(tr["TB_net"])
        if not np.isnan(sv) and not np.isnan(fv) and sv <= fv:
            print(f"  acct={a} type={atype.get(a,'?'):<10} stock_rho1={sv:+.3f} flow_rho1={fv:+.3f}  "
                  f"stock_vals={np.round(tr[STOCK_SERIES],1)} flow_vals={np.round(tr['TB_net'],1)}")

    print("\n=== rho1 validity floor: T=4 means 3 points -> rho1 uses 3 lag pairs ===")
    print("    (rho1 requires len(y)>=3; at T=4 every series is just barely valid)")

    print("\n=== closest-call AUC margin: min gap between stock and flow rho1 distributions at each T ===")
    for tt in T_GRID:
        tr = {a: truncate(full[a], tt) for a in full}
        sv = np.array([rho1(tr[a][STOCK_SERIES]) for a in full])
        fv = np.array([rho1(tr[a]["TB_net"]) for a in full])
        sv, fv = sv[~np.isnan(sv)], fv[~np.isnan(fv)]
        # overlap region: how many flow values exceed the stock 10th percentile?
        stock_p10 = np.percentile(sv, 10)
        flow_p90 = np.percentile(fv, 90)
        overlap = flow_p90 - stock_p10
        print(f"  T={tt:>2}: stock_p10={stock_p10:+.3f} flow_p90={flow_p90:+.3f} "
              f"overlap(flow_p90-stock_p10)={overlap:+.3f}  {'OVERLAP' if overlap>0 else 'clean gap'}")


if __name__ == "__main__":
    diagnose_failures()
