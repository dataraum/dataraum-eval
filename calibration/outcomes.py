"""Outcomes labeler — golden SQL vs ground truth, joined with readiness bands.

The scoreboard's three buckets per deliverable metric (S0 of the calibration
program):

    right            computed value within tolerance of ground truth
    wrong_prevented  out of tolerance AND >=1 lineage column banded non-ready
                     (the system would have warned — the product thesis held)
    wrong_delivered  out of tolerance with every lineage column banded ready
                     (the silently-wrong number — the only real failure)

Golden SQL mirrors the GENERATOR's definitions (testdata ground_truth.py):
posted journal entries inside the fiscal window; revenue = credits to 4xxx
accounts; expenses = debits to 5xxx; AR/AP/cash = cumulative debit-credit over
the fixed account sets; DSO/DPO derive from those. Authored once, validated
against CLEAN data (--offline on the clean strategy must reproduce ground
truth) — judgment at authoring time, deterministic at run time.

    uv run python -m calibration.outcomes <strategy>             # lake + bands
    uv run python -m calibration.outcomes <strategy> --offline   # CSVs, SQL check only
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import duckdb
import yaml

from calibration.tools._runs import short

EVAL_ROOT = Path(__file__).resolve().parent.parent
DELIVERABLE_SPEC = EVAL_ROOT / "deliverables" / "annual_summary.yaml"

# Logical table names the golden SQL needs, resolved per backend (lake names
# carry the src_<digest>__ upload prefix; offline reads the raw CSVs).
_TABLES = ("journal_lines", "journal_entries")

# Generator constants (testdata ground_truth.py:26-30) — the metric DEFINITIONS,
# not tunables: account-class prefixes and the balance-sheet account sets.
_REVENUE_PREFIX = "4"
_EXPENSE_PREFIX = "5"
_AR_ACCOUNTS = ("1210", "1220")
_AP_ACCOUNTS = ("2110", "2120")
_CASH_ACCOUNTS = ("1110", "1120")

# Which physical columns each metric's number flows through — the join key to
# the readiness bands. Source-prefix-stripped "table.column".
LINEAGE: dict[str, list[str]] = {
    "total_revenue": [
        "journal_lines.credit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "total_expenses": [
        "journal_lines.debit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "gross_profit": [
        "journal_lines.credit",
        "journal_lines.debit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "ending_ar_balance": [
        "journal_lines.debit",
        "journal_lines.credit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "ending_ap_balance": [
        "journal_lines.debit",
        "journal_lines.credit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "ending_cash_balance": [
        "journal_lines.debit",
        "journal_lines.credit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "annual_dso": [
        "journal_lines.credit",
        "journal_lines.debit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
    "annual_dpo": [
        "journal_lines.credit",
        "journal_lines.debit",
        "journal_lines.account_id",
        "journal_entries.status",
        "journal_entries.date",
    ],
}


def _gl_base(t: dict[str, str], window: tuple[str, str]) -> str:
    """Posted journal lines joined to their entry, inside the fiscal window."""
    return (
        f"SELECT CAST(jl.account_id AS VARCHAR) AS account_id, jl.debit, jl.credit "
        f"FROM {t['journal_lines']} jl "
        f"JOIN {t['journal_entries']} je ON jl.entry_id = je.entry_id "
        f"WHERE lower(CAST(je.status AS VARCHAR)) = 'posted' "
        f"AND CAST(je.date AS DATE) >= DATE '{window[0]}' "
        f"AND CAST(je.date AS DATE) < DATE '{window[1]}'"
    )


def _in_list(accounts: tuple[str, ...]) -> str:
    return ", ".join(f"'{a}'" for a in accounts)


def compute_metrics(
    conn: duckdb.DuckDBPyConnection, tables: dict[str, str], window: tuple[str, str]
) -> dict[str, float]:
    """Run the golden SQL; return metric id -> computed value."""
    base = _gl_base(tables, window)
    row = conn.execute(
        f"WITH gl AS ({base}) SELECT "
        f"SUM(CASE WHEN account_id LIKE '{_REVENUE_PREFIX}%' THEN credit ELSE 0 END), "
        f"SUM(CASE WHEN account_id LIKE '{_EXPENSE_PREFIX}%' THEN debit ELSE 0 END), "
        f"SUM(CASE WHEN account_id IN ({_in_list(_AR_ACCOUNTS)}) THEN debit - credit ELSE 0 END), "
        f"SUM(CASE WHEN account_id IN ({_in_list(_AP_ACCOUNTS)}) THEN credit - debit ELSE 0 END), "
        f"SUM(CASE WHEN account_id IN ({_in_list(_CASH_ACCOUNTS)}) THEN debit - credit ELSE 0 END) "
        f"FROM gl"
    ).fetchone()
    assert row is not None
    revenue, expenses, ar, ap, cash = (float(v or 0.0) for v in row)

    days = conn.execute(f"SELECT DATE '{window[1]}' - DATE '{window[0]}'").fetchone()
    total_days = int(days[0]) if days else 365

    return {
        "total_revenue": revenue,
        "total_expenses": expenses,
        "gross_profit": revenue - expenses,
        "ending_ar_balance": ar,
        "ending_ap_balance": ap,
        "ending_cash_balance": cash,
        "annual_dso": (ar / revenue * total_days) if revenue > 0 else 0.0,
        "annual_dpo": (ap / expenses * total_days) if expenses > 0 else 0.0,
    }


def _load_spec() -> dict[str, dict[str, Any]]:
    """Metric id -> {tolerance_pct | tolerance_abs} from the deliverable spec."""
    spec = yaml.safe_load(DELIVERABLE_SPEC.read_text())
    return {m["id"]: m for m in spec.get("metrics", [])}


def _load_ground_truth(strategy: str) -> dict[str, Any]:
    gt_path = EVAL_ROOT / "data" / strategy / "ground_truth.yaml"
    if not gt_path.exists():
        raise SystemExit(f"no ground truth at {gt_path} — generate the strategy first")
    loaded: dict[str, Any] = yaml.safe_load(gt_path.read_text())
    return loaded


def _fiscal_window(gt: dict[str, Any]) -> tuple[str, str]:
    start = str(gt.get("fiscal_year_start", "2025-01-01"))
    months = int(gt.get("months", 12))
    year, month = int(start[:4]), int(start[5:7])
    end_year = year + (month - 1 + months) // 12
    end_month = (month - 1 + months) % 12 + 1
    return start, f"{end_year:04d}-{end_month:02d}-01"


def _within(computed: float, expected: float, spec: dict[str, Any]) -> tuple[bool, float]:
    """(in_tolerance, deviation) under the spec's tolerance_pct or tolerance_abs."""
    deviation = computed - expected
    if "tolerance_abs" in spec:
        return abs(deviation) <= float(spec["tolerance_abs"]), deviation
    tol_pct = float(spec.get("tolerance_pct", 1.0))
    if expected == 0:
        return computed == 0, deviation
    return abs(deviation) / abs(expected) * 100.0 <= tol_pct, deviation


def _offline_tables(conn: duckdb.DuckDBPyConnection, strategy: str) -> dict[str, str]:
    """Register the raw generated CSVs as views named by their logical names."""
    data_dir = EVAL_ROOT / "data" / strategy
    out: dict[str, str] = {}
    for name in _TABLES:
        csv = data_dir / f"{name}.csv"
        if not csv.exists():
            raise SystemExit(f"missing {csv}")
        conn.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{csv}')")
        out[name] = name
    return out


def _lake_tables(run: Any) -> dict[str, str]:
    """Resolve logical names to THIS run's typed lake tables, session-scoped.

    A batch keeps several strategies' tables in ONE lake, all suffixed with the
    same logical names — suffix-matching information_schema read whichever leg
    landed last (the first batch's false 16/16-right). The sidecar's source_ids
    own exactly this strategy's tables, so resolve through the workspace
    metadata instead.
    """
    from sqlalchemy import select

    from calibration.tools._runs import workspace_session

    source_ids = set(run.source_ids)
    out: dict[str, str] = {}
    with workspace_session() as session:
        from dataraum.storage import Table

        for t in session.execute(select(Table)).scalars():
            if t.layer != "typed" or t.source_id not in source_ids or not t.duckdb_path:
                continue
            logical = short(t.table_name)
            if logical in _TABLES:
                out[logical] = f'lake.typed."{t.duckdb_path}"'
    missing = [t for t in _TABLES if t not in out]
    if missing:
        raise SystemExit(f"run's typed tables missing from metadata: {missing}")
    return out


def _non_ready_bands(strategy: str) -> dict[str, str]:
    """'table.column' -> worst non-ready band, from the loss-rollup readiness."""
    from calibration.tools.measure import _BAND_RANK, _dataset_view

    view = _dataset_view(strategy)
    out: dict[str, str] = {}
    for key, intents in view["readiness"]["non_ready_intents"].items():
        out[key] = max(intents.values(), key=lambda band: _BAND_RANK[band])
    return out


def label(strategy: str, *, offline: bool = False) -> dict[str, Any]:
    """Compute every deliverable metric and bucket it. The scoreboard row."""
    spec = _load_spec()
    gt = _load_ground_truth(strategy)
    window = _fiscal_window(gt)
    expected: dict[str, Any] = gt.get("annual", {})

    if offline:
        conn = duckdb.connect(":memory:")
        tables = _offline_tables(conn, strategy)
        computed = compute_metrics(conn, tables, window)
        bands: dict[str, str] = {}
    else:
        from calibration import runner as runner_mod
        from calibration.tools._runs import load_run

        run = load_run(strategy)  # read-only over a completed run; never triggers one
        runner_mod.bootstrap_engine()
        tables = _lake_tables(run)
        from dataraum.worker.bootstrap import (
            bootstrap_worker_substrate,
            shutdown_worker_substrate,
        )

        manager = bootstrap_worker_substrate()
        try:
            with manager.duckdb_cursor() as cursor:
                computed = compute_metrics(cursor, tables, window)
        finally:
            shutdown_worker_substrate(manager)
        bands = _non_ready_bands(strategy)

    metrics: list[dict[str, Any]] = []
    buckets = {"right": 0, "wrong_prevented": 0, "wrong_delivered": 0}
    for metric_id, value in computed.items():
        if metric_id not in expected:
            continue
        m_spec = spec.get(metric_id, {})
        ok, deviation = _within(value, float(expected[metric_id]), m_spec)
        warned = sorted({col for col in LINEAGE.get(metric_id, []) if col in bands})
        if ok:
            bucket = "right"
        elif warned and not offline:
            bucket = "wrong_prevented"
        else:
            bucket = "wrong_delivered"
        if not offline:
            buckets[bucket] += 1
        metrics.append(
            {
                "metric": metric_id,
                "expected": float(expected[metric_id]),
                "computed": round(value, 2),
                "deviation": round(deviation, 2),
                "in_tolerance": ok,
                "non_ready_lineage": {col: bands[col] for col in warned},
                **({} if offline else {"bucket": bucket}),
            }
        )

    return {
        "strategy": strategy,
        "mode": "offline" if offline else "lake",
        "fiscal_window": list(window),
        "metrics": metrics,
        **({} if offline else {"buckets": buckets}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run golden SQL on the generated CSVs (no lake, no bands) — the SQL self-check",
    )
    args = parser.parse_args()
    print(yaml.safe_dump(label(args.strategy, offline=args.offline), sort_keys=False))


if __name__ == "__main__":
    main()
