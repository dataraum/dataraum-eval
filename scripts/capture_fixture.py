#!/usr/bin/env python
"""Capture entropy-measurement INPUTS from a live run into a portable SQLite fixture.

Run ONCE per pipeline-output-shape change: bring up the docker stack, run one
``clean`` + one ``detection-v1`` pipeline, then this script extracts what the
measurements *consume* —

  * Postgres (``ws_<id>`` schema): witness distributions (pooling C/U), statistical
    profiles (null_ratio / outlier_rate / dimensional slice inputs), benford digit
    distributions + outlier detection (statistical_quality_metrics), semantic
    annotations (units / roles / null_tokens), drift summaries, and the
    measurement OUTPUTS (entropy_objects / readiness) as regression baselines.
  * the generated source CSVs in ``data/<strategy>/``: raw per-row measure values +
    categorical slice keys — what outlier_rate, benford, derived_value, and
    dimensional_entropy consume — read straight from the testdata CSVs, without
    opening the DuckLake.

…into ``calibration/fixtures/entropy_inputs.sqlite``. After this, every Tier-1/2
measure + teach unit test runs against the SQLite fixture at unit speed — no
docker, no pipeline. See ``entropy_eval_architecture.md``.

    python scripts/capture_fixture.py             # docker stack up; clean + det-v1 already run
    python scripts/capture_fixture.py --raw-only  # refresh ONLY raw_values from data/ CSVs (no docker)

``--raw-only`` rebuilds the ``raw_values`` table in place from the source CSVs and
leaves every Postgres table untouched — use it when the capture's column policy
(``_keep_columns``) changes but the pipeline output has not, so no docker / no
re-run is needed.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

import psycopg

EVAL_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = EVAL_ROOT / "calibration" / "fixtures" / "entropy_inputs.sqlite"

# Measurement-input + output tables in the ws_ schema.
PG_TABLES = [
    "claim_witnesses",  # pooling C/U inputs (witness distributions)
    "statistical_profiles",  # null_ratio / outlier_rate / dimensional slice inputs
    "statistical_quality_metrics",  # benford digit_distribution, outlier_detection
    "semantic_annotations",  # units, roles, null_tokens
    "column_drift_summaries",  # drift summaries (raw per-period values come from CSV)
    "entropy_objects",  # measurement OUTPUTS (regression baseline)
    "entropy_readiness",  # readiness OUTPUTS
]

# Strategies whose generated source CSVs carry the raw per-period values.
# detection-null-v1 carries the inject_null_tokens columns (journal_lines.debit,
# bank_transactions.amount) — the raw sentinel values behind the pooled witnesses.
STRATEGIES = ["clean", "detection-v1", "detection-null-v1", "detection-typing-v1"]


def _cell(value: Any) -> Any:
    """SQLite-storable form: JSON for dict/list, pass scalars through."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _workspace_schema(strategy: str) -> str:
    """The ``ws_<id>`` schema *strategy*'s pipeline wrote (DAT-508).

    Each strategy owns a deterministic workspace (``runner.workspace_id_for``, the
    same uuid5 the runner activates), so the capture discovers the schema exactly
    the way the calibration tools resolve it — never a hardcoded legacy id.
    """
    from dataraum.server.workspace import schema_name_for

    from calibration.runner import workspace_id_for

    return schema_name_for(workspace_id_for(strategy))


def capture_pg(sqlite_conn: sqlite3.Connection) -> None:
    """Capture each strategy's workspace tables, tagged with a ``strategy`` column.

    Post-DAT-508 every strategy runs in its OWN ``ws_<id>`` schema, so the fixture
    unions the per-strategy rows (the pre-DAT-508 capture read one shared schema
    that held every session's rows — consumers still see the union, now labelled).
    A strategy whose schema is absent is reported and skipped; capturing NOTHING
    overall (no schema, or schemas with zero rows) aborts loudly — a silently
    empty committed fixture would fail every Tier-2 test confusingly later.
    """
    from calibration import stack

    dsn = (
        f"host={stack.POSTGRES_HOST} port={stack.POSTGRES_PORT} dbname={stack.POSTGRES_DB} "
        f"user={stack.POSTGRES_USER} password={stack.POSTGRES_PASSWORD}"
    )
    for table in PG_TABLES:
        sqlite_conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    created: set[str] = set()
    total_rows = 0
    with psycopg.connect(dsn) as pg:
        for strat in STRATEGIES:
            schema = _workspace_schema(strat)
            known = pg.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,)
            ).fetchone()
            if known is None:
                print(f"  !! schema {schema} for '{strat}' missing — run its pipeline first")
                continue
            for table in PG_TABLES:
                cur = pg.execute(f'SELECT * FROM "{schema}"."{table}"')  # noqa: S608 (fixed names)
                cols = [d.name for d in cur.description or []]
                rows = cur.fetchall()
                total_rows += len(rows)
                if table not in created:
                    coldefs = ", ".join(f'"{c}" TEXT' for c in ["strategy", *cols])
                    sqlite_conn.execute(f'CREATE TABLE "{table}" ({coldefs})')
                    created.add(table)
                placeholders = ", ".join("?" for _ in ["strategy", *cols])
                sqlite_conn.executemany(
                    f'INSERT INTO "{table}" VALUES ({placeholders})',
                    [[strat, *(_cell(v) for v in r)] for r in rows],
                )
                print(f"  pg.{table} [{strat}]: {len(rows)} rows ({len(cols)} cols)")
    if not created:
        raise SystemExit(
            "capture_pg: NO strategy workspace schema exists — nothing captured; run "
            f"the pipelines first ({', '.join(STRATEGIES)})"
        )
    if total_rows == 0:
        raise SystemExit(
            "capture_pg: workspace schemas exist but hold ZERO rows across every "
            "captured table — the pipelines have not run in these workspaces; "
            "refusing to write an empty fixture"
        )


# A non-numeric, non-date string column counts as a categorical SLICE KEY only if
# its distinct-value count over the sample is at or below this — currency,
# cost_center, status, account_type qualify; free text (description) and
# high-cardinality identifiers do not.
_MAX_SLICE_CARDINALITY = 25

# FK columns retained for referential-integrity grounding (relationship_entropy).
# Identifiers are otherwise dropped (high-cardinality, not a per-column measure) —
# but these specific parent/child keys ARE what relationship_entropy consumes: the
# grounding net measures the orphan rate (a child key with no matching parent), so
# the fixture must carry BOTH sides of each graded relationship. Keyed by table
# stem; kept regardless of type or cardinality (an id is all-distinct by design).
_FK_COLUMNS: dict[str, list[str]] = {
    "payments": ["invoice_id"],  # child: FK → invoices.invoice_id (break_referential_integrity)
    "invoices": ["invoice_id"],  # parent: the referenced key
}

# A column is a NUMERIC measure if at least this fraction of its non-null sampled
# values parse as float. Majority-based, not first-value: a numeric measure with
# type corruption (corrupt_types dropping VARCHAR garbage into 15% of debit) is
# STILL a measure — that's exactly what type_fidelity grades, so the fixture must
# keep it. A genuine categorical (currency, status) sits near 0.0, far below this.
_NUMERIC_FRACTION = 0.6


def _fraction_float(values: list[str]) -> float:
    """Fraction of ``values`` that parse as float (0.0 for an empty list)."""
    if not values:
        return 0.0
    ok = 0
    for v in values:
        try:
            float(v)
        except (TypeError, ValueError):
            continue
        ok += 1
    return ok / len(values)


def _keep_columns(rows: list[dict[str, str]], source: str = "") -> list[str]:
    """Measure + slice-key columns — what the recorded measures consume. Keeps
    numeric measures (outlier_rate / benford / derived_value), date columns (when
    present), low-cardinality categorical slice keys (dimensional_entropy /
    slice-conditional null), and any declared FK column for ``source``
    (relationship_entropy's orphan-rate grounding). Drops other identifiers, free
    text, and high-cardinality strings so the committed fixture stays small.

    Returns [] only when the table has NO numeric measure AND no declared FK key (a
    pure dimension table like chart_of_accounts carries nothing the recorded
    measures use). A date is NO LONGER required (temporal_drift was CUT, DAT-442): a
    numeric fact table whose date lives in a parent — journal_lines →
    journal_entries — is now KEPT for its measures + slice keys instead of being
    skipped for want of a time axis.
    """
    if not rows:
        return []
    fk_keep = [c for c in _FK_COLUMNS.get(source, []) if c in rows[0]]
    sample = rows[: min(200, len(rows))]
    dates, numerics, categoricals = [], [], []
    for col in rows[0]:
        if col in fk_keep:
            continue  # retained below as a referential key, regardless of type/cardinality
        if col.lower() == "id" or col.lower().endswith("_id"):
            continue  # other identifiers are not measures or slice keys
        values = [r[col] for r in sample if r.get(col)]
        first = values[0] if values else None
        if first is None:
            continue
        # Majority-numeric → a measure, even with corrupt cells mixed in (type_fidelity).
        if _fraction_float(values) >= _NUMERIC_FRACTION:
            numerics.append(col)
            continue
        if len(first) >= 7 and first[:4].isdigit() and first[4] in "-/":  # date-like
            dates.append(col)
            continue
        # Non-numeric, non-date string: a categorical slice key iff low-cardinality
        # (not free text, not an id-like all-distinct column).
        distinct = len(set(values))
        if distinct <= _MAX_SLICE_CARDINALITY and distinct < len(values):
            categoricals.append(col)
    # No numeric measure AND no referential key → nothing the recorded measures consume.
    if not numerics and not fk_keep:
        return []
    return dates + numerics + categoricals + fk_keep


def capture_raw_values(sqlite_conn: sqlite3.Connection) -> None:
    """Per-row numeric/date source values per (strategy, table) — drift's real CDFs."""
    sqlite_conn.execute("DROP TABLE IF EXISTS raw_values")
    sqlite_conn.execute("CREATE TABLE raw_values (strategy TEXT, source TEXT, row_json TEXT)")
    for strat in STRATEGIES:
        data_dir = EVAL_ROOT / "data" / strat
        if not data_dir.exists():
            print(f"  !! {data_dir} missing — run the pipeline for '{strat}' first")
            continue
        for csv_path in sorted(data_dir.glob("*.csv")):
            with csv_path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            keep = _keep_columns(rows, csv_path.stem)
            if not keep:
                continue  # no numeric/date column → nothing drift/benford can use
            out = [(strat, csv_path.stem, json.dumps({c: r[c] for c in keep})) for r in rows]
            sqlite_conn.executemany("INSERT INTO raw_values VALUES (?, ?, ?)", out)
            print(f"  raw.{strat}/{csv_path.stem}: {len(out)} rows, cols={keep}")


def main(raw_only: bool = False) -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if raw_only:
        if not FIXTURE.exists():
            raise SystemExit(
                f"--raw-only needs an existing fixture ({FIXTURE.name}); run a full "
                "capture first (docker stack + clean + detection-v1)."
            )
        conn = sqlite3.connect(FIXTURE)
        print(f"[capture] --raw-only: refreshing raw_values in {FIXTURE} (PG tables untouched)")
        capture_raw_values(conn)
        conn.commit()
        conn.close()
        kb = FIXTURE.stat().st_size // 1024
        print(f"[capture] done — {FIXTURE.name} ({kb} KB)")
        return

    FIXTURE.unlink(missing_ok=True)
    conn = sqlite3.connect(FIXTURE)
    print(f"[capture] → {FIXTURE}")
    print("[capture] Postgres measurement-input/output tables:")
    capture_pg(conn)
    print("[capture] raw source values (measures + slice keys on real data):")
    capture_raw_values(conn)
    conn.commit()
    conn.close()
    kb = FIXTURE.stat().st_size // 1024
    print(f"[capture] done — {FIXTURE.name} ({kb} KB)")


if __name__ == "__main__":
    import sys

    main(raw_only="--raw-only" in sys.argv[1:])
