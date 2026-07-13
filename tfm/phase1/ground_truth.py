"""DAT-743 Phase 1: DGP ground truth, codified from testdata source (2026-07-13).

Every fact here was read from vendor/dataraum-testdata code, not assumed.
File references are to that repo.

P2 (structure recovery)
    journal_lines.net_amount = debit - credit, exactly (models.py:81-85,
    a pydantic computed_field). No other column enters the formula.
    trial_balance.debit_balance  = sum(journal_lines.debit)  and
    trial_balance.credit_balance = sum(journal_lines.credit) over the lines
    whose entry is POSTED, grouped by (account_id, period=entry month)
    (generators.py:1055-1102). Grouping keys are not value drivers.

P4 (exogenous conditioning)
    There is NO fx->amount coupling in clean generation: fx_rates is a
    standalone table; every amount is drawn in USD (generators.py:1023-1049;
    no consumer of FXRate exists). Providing fx columns therefore CANNOT add
    real signal -> fx is a negative control. Measured "lift" from fx
    conditioning on clean data is noise-fitting by construction.
    The constructed calendar sensitivity that DOES exist: Q4 sales-count
    boost, q4_seasonal_boost=0.3 (generators.py:303-304) -> revenue-account
    activity is seasonally elevated in Oct-Dec.

P3 (anomaly labels)
    entropy_map.yaml: {injections: [...], total_injections: N}; each record
    carries target_file, target_column, target_rows (0-based dataframe row
    indices at injection time = CSV data-row order), injection_type,
    severity, detector_id (registry.py:12-26, export.py:172-182).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

TFM_DATA = Path(__file__).resolve().parents[2] / "data" / "tfm"

# ------------------------------------------------------------------ P2 truth
# Formula membership per target: feature -> 1.0 (in the DGP formula) / 0.0.
# Features not listed score 0. Derivative-but-correlated features (e.g. a
# line count) are deliberately 0 — the probe grades recovery of the
# constructed formula, and the findings discuss the correlated ones.

NET_AMOUNT_FORMULA = {"debit": 1.0, "credit": 1.0}
TB_DEBIT_FORMULA = {"sum_debit": 1.0}
TB_CREDIT_FORMULA = {"sum_credit": 1.0}

# ------------------------------------------------------------------ P4 truth
Q4_SEASONAL_BOOST = 0.3  # sales-count uplift in Oct/Nov/Dec (generators.py:303)
FX_IS_COUPLED = False  # fx_rates never feeds any amount in clean generation


# ------------------------------------------------------------------ P3 labels

def load_entropy_map(corpus_dir: Path) -> list[dict]:
    with (corpus_dir / "entropy_map.yaml").open() as fh:
        payload = yaml.safe_load(fh)
    return payload["injections"]


def row_labels(corpus_dir: Path, table: str) -> pd.DataFrame:
    """Per-row anomaly labels for one table of one corpus.

    Returns a frame indexed like the table's CSV data rows with columns:
    ``label`` (0/1 any injection touched the row), and one 0/1 column per
    ``injection_type`` present. Schema-level injections (empty target_rows,
    e.g. obscure_column_names) contribute no row labels.
    """
    n_rows = _table_len(corpus_dir, table)
    out = pd.DataFrame({"label": np.zeros(n_rows, dtype=int)})
    for inj in load_entropy_map(corpus_dir):
        if inj["target_file"] != f"{table}.csv" or not inj["target_rows"]:
            continue
        rows = [r for r in inj["target_rows"] if r < n_rows]
        kind = inj["injection_type"]
        if kind not in out.columns:
            out[kind] = 0
        out.loc[rows, kind] = 1
        out.loc[rows, "label"] = 1
    return out


def injection_summary(corpus_dir: Path) -> pd.DataFrame:
    rows = [
        {
            "injection_id": inj["injection_id"],
            "table": inj["target_file"].removesuffix(".csv"),
            "column": inj["target_column"],
            "type": inj["injection_type"],
            "severity": inj["severity"],
            "detector_id": inj["detector_id"],
            "n_rows": len(inj["target_rows"]),
        }
        for inj in load_entropy_map(corpus_dir)
    ]
    return pd.DataFrame(rows)


def _table_len(corpus_dir: Path, table: str) -> int:
    with (corpus_dir / f"{table}.csv").open() as fh:
        return sum(1 for _ in fh) - 1  # header


if __name__ == "__main__":
    for name in ("p3-low-s42", "p3-medium-s42", "p3-high-s42"):
        print(f"=== {name}")
        print(injection_summary(TFM_DATA / name).to_string(index=False))
