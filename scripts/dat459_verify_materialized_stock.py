"""DAT-459 — verify the MATERIALIZED stock reads as stock under the reconciliation witness.

Closes the testdata leg: confirm on the freshly generated corpus that
  - balance_sheet.ending_balance      reconciles as STOCK  (Δvalue ≈ net movement; carry-forward)
  - trial_balance.debit_balance       reconciles as FLOW   (value ≈ gross debit movement; per-period)
against the INDEPENDENT per-period movements from journal_lines. This is the recall(flow-claimed-as-
balance fires) / precision(genuine stock quiet) substrate the engine detector + eval tests build on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data/clean")


def _pk(p: str) -> tuple[int, int]:
    y, m = p.split("-")
    return int(y), int(m)


def gl_movements() -> pd.DataFrame:
    jl = pd.read_csv(DATA / "journal_lines.csv", dtype={"account_id": str, "entry_id": str})
    je = pd.read_csv(DATA / "journal_entries.csv", dtype={"entry_id": str})
    je["period"] = pd.to_datetime(je["date"]).dt.strftime("%Y-%m")
    if "status" in je.columns:
        je = je[je["status"].astype(str).str.lower() == "posted"]
    g = jl.merge(je[["entry_id", "period"]], on="entry_id", how="inner")
    out = g.groupby(["account_id", "period"], as_index=False).agg(
        gross_debit=("debit", "sum"), net=("debit", "sum")
    )
    cr = g.groupby(["account_id", "period"], as_index=False)["credit"].sum()
    out = out.merge(cr, on=["account_id", "period"])
    out["net"] = out["debit" if "debit" in out else "gross_debit"] - out["credit"]
    return out


def reconcile(y: np.ndarray, m: np.ndarray) -> str:
    denom = np.sum(np.abs(m)) or 1.0
    r_flow = np.sum(np.abs(y - m)) / denom
    r_stock = np.sum(np.abs(np.diff(y) - m[1:])) / (np.sum(np.abs(m[1:])) or 1.0)
    return "stock" if r_stock < r_flow else "flow"


def main() -> None:
    gl = gl_movements()
    gl_by = {(r.account_id, r.period): (float(r.gross_debit), float(r.net)) for r in gl.itertuples()}

    results = {}

    # balance_sheet.ending_balance — expect STOCK, anchor = net movement
    bs = pd.read_csv(DATA / "balance_sheet.csv", dtype={"account_id": str})
    stock_labels = []
    for acct, g in bs.groupby("account_id"):
        g = g.sort_values("period", key=lambda s: s.map(_pk))
        y = g["ending_balance"].to_numpy(float)
        m = np.array([gl_by.get((acct, p), (0.0, 0.0))[1] for p in g["period"]])
        if len(y) >= 4 and np.sum(np.abs(m)) > 0:
            stock_labels.append(reconcile(y, m))
    results["balance_sheet.ending_balance (expect stock)"] = stock_labels

    # trial_balance.debit_balance — expect FLOW, anchor = gross debit movement
    tb = pd.read_csv(DATA / "trial_balance.csv", dtype={"account_id": str})
    flow_labels = []
    for acct, g in tb.groupby("account_id"):
        g = g.sort_values("period", key=lambda s: s.map(_pk))
        y = g["debit_balance"].to_numpy(float)
        m = np.array([gl_by.get((acct, p), (0.0, 0.0))[0] for p in g["period"]])
        if len(y) >= 4 and np.sum(np.abs(m)) > 0:
            flow_labels.append(reconcile(y, m))
    results["trial_balance.debit_balance (expect flow)"] = flow_labels

    print(f"DATA={DATA}")
    for name, labels in results.items():
        expect = "stock" if "stock" in name else "flow"
        acc = np.mean([x == expect for x in labels]) if labels else float("nan")
        from collections import Counter
        print(f"  {name:<46} n={len(labels):>3}  acc={acc:5.1%}  {dict(Counter(labels))}")


if __name__ == "__main__":
    main()
