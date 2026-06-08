#!/usr/bin/env python
"""Capture entropy-measurement INPUTS from a live run into a portable SQLite fixture.

Run ONCE per pipeline-output-shape change: bring up the docker stack, run one
``clean`` + one ``detection-v1`` pipeline, then this script extracts what the
measurements *consume* —

  * Postgres (``ws_<id>`` schema): witness distributions (pooling C/U), statistical
    profiles (null_ratio / outlier_rate / slice_variance), benford digit
    distributions + outlier detection (statistical_quality_metrics), semantic
    annotations (units / roles / null_tokens), drift summaries, and the
    measurement OUTPUTS (entropy_objects / readiness) as regression baselines.
  * the generated source CSVs in ``data/<strategy>/``: the raw per-period values
    drift (KS) needs — the DuckLake slice values, without opening the lake.

…into ``calibration/fixtures/entropy_inputs.sqlite``. After this, every Tier-1/2
measure + teach unit test runs against the SQLite fixture at unit speed — no
docker, no pipeline. See ``entropy_eval_architecture.md``.

    python scripts/capture_fixture.py        # docker stack up; clean + det-v1 already run
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

import psycopg

EVAL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "ws_00000000_0000_0000_0000_000000000001"
FIXTURE = EVAL_ROOT / "calibration" / "fixtures" / "entropy_inputs.sqlite"

# Measurement-input + output tables in the ws_ schema.
PG_TABLES = [
    "claim_witnesses",  # pooling C/U inputs (witness distributions)
    "statistical_profiles",  # null_ratio / outlier_rate / slice_variance inputs
    "statistical_quality_metrics",  # benford digit_distribution, outlier_detection
    "semantic_annotations",  # units, roles, null_tokens
    "column_drift_summaries",  # drift summaries (raw per-period values come from CSV)
    "entropy_objects",  # measurement OUTPUTS (regression baseline)
    "entropy_readiness",  # readiness OUTPUTS
]

# Strategies whose generated source CSVs carry the raw per-period values.
STRATEGIES = ["clean", "detection-v1"]


def _pg_password() -> str:
    for line in (EVAL_ROOT / ".docker.env").read_text().splitlines():
        if line.startswith("POSTGRES_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("POSTGRES_PASSWORD not found in .docker.env")


def _cell(value: Any) -> Any:
    """SQLite-storable form: JSON for dict/list, pass scalars through."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def capture_pg(sqlite_conn: sqlite3.Connection) -> None:
    dsn = (
        f"host=localhost port=5432 dbname=dataraum user=dataraum "
        f"password={_pg_password()}"
    )
    with psycopg.connect(dsn) as pg:
        for table in PG_TABLES:
            cur = pg.execute(f'SELECT * FROM {SCHEMA}."{table}"')  # noqa: S608 (fixed names)
            cols = [d.name for d in cur.description or []]
            rows = cur.fetchall()
            coldefs = ", ".join(f'"{c}" TEXT' for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            sqlite_conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            sqlite_conn.execute(f'CREATE TABLE "{table}" ({coldefs})')
            sqlite_conn.executemany(
                f'INSERT INTO "{table}" VALUES ({placeholders})',
                [[_cell(v) for v in r] for r in rows],
            )
            print(f"  pg.{table}: {len(rows)} rows ({len(cols)} cols)")


def _keep_columns(rows: list[dict[str, str]]) -> list[str]:
    """Numeric measure + date columns only — what drift/benford consume. Drops ids,
    descriptions, free text so the committed fixture stays small. Returns [] unless
    the table has at least one real numeric measure (a date-only table is useless)."""
    if not rows:
        return []
    sample = rows[: min(50, len(rows))]
    dates, numerics = [], []
    for col in rows[0]:
        if col.lower() == "id" or col.lower().endswith("_id"):
            continue  # identifiers are not measures
        first = next((r[col] for r in sample if r.get(col)), None)
        if first is None:
            continue
        try:
            float(first)
            numerics.append(col)
            continue
        except ValueError:
            pass
        if len(first) >= 7 and first[:4].isdigit() and first[4] in "-/":  # date-like
            dates.append(col)
    # Need BOTH a time axis and a measure to be useful for time-drift; a table
    # whose date lives in a parent (e.g. journal_lines → journal_entries) is
    # skipped here rather than dumped without a usable time column.
    return dates + numerics if (dates and numerics) else []


def capture_raw_values(sqlite_conn: sqlite3.Connection) -> None:
    """Per-row numeric/date source values per (strategy, table) — drift's real CDFs."""
    sqlite_conn.execute("DROP TABLE IF EXISTS raw_values")
    sqlite_conn.execute(
        "CREATE TABLE raw_values (strategy TEXT, source TEXT, row_json TEXT)"
    )
    for strat in STRATEGIES:
        data_dir = EVAL_ROOT / "data" / strat
        if not data_dir.exists():
            print(f"  !! {data_dir} missing — run the pipeline for '{strat}' first")
            continue
        for csv_path in sorted(data_dir.glob("*.csv")):
            with csv_path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            keep = _keep_columns(rows)
            if not keep:
                continue  # no numeric/date column → nothing drift/benford can use
            out = [
                (strat, csv_path.stem, json.dumps({c: r[c] for c in keep})) for r in rows
            ]
            sqlite_conn.executemany("INSERT INTO raw_values VALUES (?, ?, ?)", out)
            print(f"  raw.{strat}/{csv_path.stem}: {len(out)} rows, cols={keep}")


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.unlink(missing_ok=True)
    conn = sqlite3.connect(FIXTURE)
    print(f"[capture] → {FIXTURE}")
    print("[capture] Postgres measurement-input/output tables:")
    capture_pg(conn)
    print("[capture] raw source values (drift / benford on real data):")
    capture_raw_values(conn)
    conn.commit()
    conn.close()
    kb = FIXTURE.stat().st_size // 1024
    print(f"[capture] done — {FIXTURE.name} ({kb} KB)")


if __name__ == "__main__":
    main()
