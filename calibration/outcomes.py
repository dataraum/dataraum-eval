"""Outcomes labeler — golden SQL vs ground truth, joined with readiness bands.

The scoreboard's three buckets per deliverable metric (S0 of the calibration
program):

    right            computed value within tolerance of ground truth
    wrong_prevented  out of tolerance AND >=1 lineage column banded non-ready
                     (the system would have warned — the product thesis held)
    wrong_delivered  out of tolerance with every lineage column banded ready
                     (the silently-wrong number — the only real failure)

Each prevention additionally carries an ATTRIBUTION (B3): ``causal`` when a
warned lineage column is itself an injected column AND its band was driven by
the detector the injection targets (the warning names the actual corruption);
``related`` when the banding detector matches an injection elsewhere in the
strategy (the watcher fired for the injected failure mode, anchored to a
connected column — the validation fan-out pattern); ``coincidental`` otherwise
(warned for a reason unrelated to any injection — still a prevention, headline
unchanged, but it would not survive that unrelated reason being fixed).
Banding detectors come from the loss rollup's own ranked intent drivers;
injected columns from the generator's entropy_map.

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
    "journal_balanced": [
        "journal_lines.credit",
        "journal_lines.debit",
        "journal_entries.status",
        "journal_entries.date",
    ],
}


def _gl_base(t: dict[str, str], window: tuple[str, str]) -> str:
    """Posted journal lines joined to their entry, inside the fiscal window.

    ``debit``/``credit`` are TRY_CAST to DOUBLE, not read raw: a type-corruption
    strategy (``corrupt_types`` on journal_lines.debit) leaves VARCHAR garbage in the
    column, and a raw ``THEN debit ELSE 0`` then mixes VARCHAR with the INTEGER literal
    and the DuckDB binder throws before this labeler can report. TRY_CAST turns each
    corrupted cell into NULL (SUM skips it), so the golden SQL runs, the deviation IS
    the injection, and the caller reports + stands down on injected strategies.
    """
    return (
        f"SELECT CAST(jl.account_id AS VARCHAR) AS account_id, "
        f"TRY_CAST(jl.debit AS DOUBLE) AS debit, TRY_CAST(jl.credit AS DOUBLE) AS credit "
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
) -> dict[str, Any]:
    """Run the golden SQL; return metric id -> computed value."""
    base = _gl_base(tables, window)
    row = conn.execute(
        f"WITH gl AS ({base}) SELECT "
        f"SUM(CASE WHEN account_id LIKE '{_REVENUE_PREFIX}%' THEN credit ELSE 0 END), "
        f"SUM(CASE WHEN account_id LIKE '{_EXPENSE_PREFIX}%' THEN debit ELSE 0 END), "
        f"SUM(CASE WHEN account_id IN ({_in_list(_AR_ACCOUNTS)}) THEN debit - credit ELSE 0 END), "
        f"SUM(CASE WHEN account_id IN ({_in_list(_AP_ACCOUNTS)}) THEN credit - debit ELSE 0 END), "
        f"SUM(CASE WHEN account_id IN ({_in_list(_CASH_ACCOUNTS)}) THEN debit - credit ELSE 0 END), "
        f"SUM(debit), SUM(credit) "
        f"FROM gl"
    ).fetchone()
    assert row is not None
    revenue, expenses, ar, ap, cash, total_debit, total_credit = (float(v or 0.0) for v in row)
    # The double-entry invariant as a boolean: balanced within 0.1% of the
    # larger side (the generator quantizes to cents; injections that corrupt
    # amounts can break it — that's the measurement, not noise).
    magnitude = max(abs(total_debit), abs(total_credit), 1.0)
    journal_balanced = abs(total_debit - total_credit) / magnitude <= 0.001

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
        "journal_balanced": journal_balanced,
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
        # Exact float equality at zero is meaningless; a cent of drift counts
        # as zero (review wave-1 nit).
        return abs(computed) <= 0.01, deviation
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
    """Resolve logical names to the workspace's current typed lake tables.

    A batch keeps several strategies' tables in ONE lake, all suffixed with the
    same logical names — suffix-matching information_schema read whichever leg
    landed last (the first batch's false 16/16-right). Source ids are NOT the
    axis either: sources are content-keyed (``src_<digest>``, re-upload dedup),
    so every file a strategy does not inject shares its Source row with the
    other legs. Post-DAT-506/508 the engine's own identity is the workspace
    **catalog head**: begin_session anchors its typed tables in ``run_tables``
    and promotes the ``(catalog, "catalog")`` head — resolve through that. (One
    eval workspace runs one strategy at a time, so the catalog head IS this
    strategy's typed selection; ``run`` is accepted for call-site symmetry.)
    """
    from sqlalchemy import select

    from calibration.tools._runs import workspace_session

    out: dict[str, str] = {}
    with workspace_session() as session:
        from dataraum.investigation.queries import tables_for_run
        from dataraum.storage import Table
        from dataraum.storage.snapshot_head import catalog_head_target, head_run_id

        catalog_run = head_run_id(session, catalog_head_target(), "catalog")
        if catalog_run is None:
            raise SystemExit("no promoted catalog head — run the pipeline before reading outcomes")
        table_ids = set(tables_for_run(session, catalog_run))
        for t in session.execute(select(Table).where(Table.table_id.in_(table_ids))).scalars():
            if t.layer != "typed" or not t.duckdb_path:
                continue
            logical = short(t.table_name)
            if logical in _TABLES:
                out[logical] = f'lake.typed."{t.duckdb_path}"'
    missing = [t for t in _TABLES if t not in out]
    if missing:
        raise SystemExit(f"catalog-head typed tables missing from metadata: {missing}")
    return out


def _non_ready_lineage(strategy: str) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Per warned 'table.column': worst non-ready band + the detectors that banded it.

    Banding detectors come from the rollup's own ranked drivers (intent risk is the
    max over measurements, so each listed driver's contribution alone reaches a
    non-ready band) — never re-derived from scores here.
    """
    from calibration.tools.measure import _BAND_RANK, _dataset_view

    view = _dataset_view(strategy)
    bands: dict[str, str] = {}
    detectors: dict[str, set[str]] = {}
    for key, intents in view["readiness"]["non_ready_intents"].items():
        bands[key] = max(intents.values(), key=lambda band: _BAND_RANK[band])
        per_intent = view["readiness"]["non_ready_drivers"].get(key, {})
        detectors[key] = {d["detector"] for ds in per_intent.values() for d in ds}
    return bands, detectors


def _injected_lineage(strategy: str) -> dict[str, set[str]]:
    """'table.column' -> detector ids the strategy's injections target there.

    The entropy_map is the generator's own record of what was corrupted where —
    the ground truth a CAUSAL prevention must match: the warning came from the
    injected column, raised by the detector the injection targets.
    """
    emap_path = EVAL_ROOT / "data" / strategy / "entropy_map.yaml"
    if not emap_path.exists():
        return {}
    emap = yaml.safe_load(emap_path.read_text()) or {}
    out: dict[str, set[str]] = {}
    for inj in emap.get("injections", []):
        table = Path(str(inj.get("target_file", ""))).stem
        column = inj.get("target_column")
        detector = inj.get("detector_id")
        if table and column and detector:
            out.setdefault(f"{table}.{column}", set()).add(str(detector))
    return out


def _attribute_prevention(
    warned: list[str],
    banding: dict[str, set[str]],
    injected: dict[str, set[str]],
) -> tuple[str, list[str]]:
    """('causal' | 'related' | 'coincidental', the columns carrying the causal warning).

    Causal: some warned lineage column is itself an injected column AND its band
    was driven by a detector the injection targets — the system warned on the
    corrupted input for the corruption's own reason. Related: the banding
    detector matches an injection's detector elsewhere in the strategy — the
    watcher fired for the injected FAILURE MODE but anchored the warning to a
    connected column (the validation fan-out pattern: TB↔GL tampering banding
    the GL columns that participate in the broken identity). Coincidental: the
    band has no relation to any injection (e.g. clean-data hedging). All three
    prevent — the headline bucket is deliberately reason-agnostic — but the
    split makes prevention quality measurable. Limitation, kept inspectable via
    banding_detectors: 'related' matches at detector granularity, so a noise
    band from a detector that also happens to be injected elsewhere would be
    over-credited.
    """
    causal_cols = sorted(
        col for col in warned if banding.get(col, set()) & injected.get(col, set())
    )
    if causal_cols:
        return "causal", causal_cols
    strategy_detectors = set().union(*injected.values()) if injected else set()
    banding_anywhere = {d for col in warned for d in banding.get(col, set())}
    if banding_anywhere & strategy_detectors:
        return "related", []
    return "coincidental", []


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
        banding: dict[str, set[str]] = {}
        injected: dict[str, set[str]] = {}
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
        bands, banding = _non_ready_lineage(strategy)
        injected = _injected_lineage(strategy)

    # The SPEC drives scoring (review wave-1): a computed metric absent from
    # the deliverable spec is never scored under a silent default tolerance;
    # a declared metric the labeler cannot compute is reported as a gap.
    # wrong_prevented is deliberately reason-agnostic: ANY non-ready band on a
    # lineage column means a practitioner is warned before trusting the number
    # — prevention does not require the band to name the metric's root cause.
    # The causal/related/coincidental split (B3) measures prevention QUALITY
    # without touching the headline: causal warned on the injected column for
    # the injection's own detector; related warned by the injected failure
    # mode anchored to a connected column; coincidental warned for an
    # unrelated reason and would not survive that reason being fixed.
    metrics: list[dict[str, Any]] = []
    buckets = {"right": 0, "wrong_prevented": 0, "wrong_delivered": 0}
    attribution_counts = {"causal": 0, "related": 0, "coincidental": 0}
    for metric_id, m_spec in spec.items():
        if metric_id not in computed:
            metrics.append({"metric": metric_id, "skipped": "no golden computation"})
            continue
        value = computed[metric_id]
        if m_spec.get("type") == "boolean":
            ok = bool(value) == bool(m_spec.get("expected", True))
            expected_val: Any = bool(m_spec.get("expected", True))
            deviation = 0.0
        else:
            if metric_id not in expected:
                metrics.append({"metric": metric_id, "skipped": "no ground-truth value"})
                continue
            expected_val = float(expected[metric_id])
            ok, deviation = _within(float(value), expected_val, m_spec)
        warned = sorted({col for col in LINEAGE.get(metric_id, []) if col in bands})
        if ok:
            bucket = "right"
        elif warned and not offline:
            bucket = "wrong_prevented"
        else:
            bucket = "wrong_delivered"
        if not offline:
            buckets[bucket] += 1
        prevention: dict[str, Any] = {}
        if bucket == "wrong_prevented":
            attribution, causal_cols = _attribute_prevention(warned, banding, injected)
            attribution_counts[attribution] += 1
            prevention = {
                "attribution": attribution,
                "banding_detectors": {col: sorted(banding.get(col, set())) for col in warned},
                **({"causal_columns": causal_cols} if causal_cols else {}),
            }
        metrics.append(
            {
                "metric": metric_id,
                "expected": expected_val,
                "computed": value if isinstance(value, bool) else round(float(value), 2),
                "deviation": round(deviation, 2),
                "in_tolerance": ok,
                "non_ready_lineage": {col: bands[col] for col in warned},
                **({} if offline else {"bucket": bucket}),
                **({"prevention": prevention} if prevention else {}),
            }
        )

    return {
        "strategy": strategy,
        "mode": "offline" if offline else "lake",
        "fiscal_window": list(window),
        "metrics": metrics,
        **({} if offline else {"buckets": buckets}),
        **({} if offline else {"prevention_attribution": attribution_counts}),
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
