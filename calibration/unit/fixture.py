"""Tier-2 recorded-fixture loader — real pipeline inputs, no docker.

Reads ``calibration/fixtures/entropy_inputs.sqlite`` (captured once by
``scripts/capture_fixture.py``). Measure + teach unit tests run against this at
unit speed. See ``entropy_eval_architecture.md``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "entropy_inputs.sqlite"


def load_fixture() -> sqlite3.Connection:
    if not FIXTURE.exists():
        raise FileNotFoundError(
            f"{FIXTURE} missing — run `python scripts/capture_fixture.py` once "
            "(docker stack + one clean + detection-v1 pipeline)."
        )
    conn = sqlite3.connect(f"file:{FIXTURE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def period_values(
    conn: sqlite3.Connection,
    strategy: str,
    source: str,
    value_col: str,
    date_col: str,
    *,
    grain: int = 7,  # YYYY-MM monthly buckets (10 = daily)
) -> list[list[float]]:
    """Recorded per-period numeric values for one column, in time order.

    Mirrors what the pipeline's monthly slicing feeds the drift measure — but read
    straight from the frozen source values, so a drift statistic is testable in
    milliseconds instead of a 10-minute pipeline run.
    """
    rows = conn.execute(
        "SELECT row_json FROM raw_values WHERE strategy=? AND source=?",
        (strategy, source),
    ).fetchall()
    by_period: dict[str, list[float]] = {}
    for (row_json,) in rows:
        rec = json.loads(row_json)
        raw, day = rec.get(value_col), rec.get(date_col)
        if raw in (None, "") or not day:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        by_period.setdefault(day[:grain], []).append(val)
    return [by_period[p] for p in sorted(by_period)]


def column_values(
    conn: sqlite3.Connection,
    strategy: str,
    source: str,
    value_col: str,
) -> list[float]:
    """All numeric values of one column for a (strategy, source), row order preserved.

    For fact tables with no time axis (journal_lines, whose date lives in its
    journal_entries parent), where ``period_values`` does not apply. This is what
    outlier_rate / derived_value / dimensional_entropy read. Non-numeric and empty
    cells are skipped.
    """
    rows = conn.execute(
        "SELECT row_json FROM raw_values WHERE strategy=? AND source=?",
        (strategy, source),
    ).fetchall()
    out: list[float] = []
    for (row_json,) in rows:
        raw = json.loads(row_json).get(value_col)
        if raw in (None, ""):
            continue
        try:
            out.append(float(raw))
        except (TypeError, ValueError):
            continue
    return out


def grouped_values(
    conn: sqlite3.Connection,
    strategy: str,
    source: str,
    value_col: str,
    slice_col: str,
) -> dict[str, list[float]]:
    """Numeric ``value_col`` grouped by categorical ``slice_col`` (a slice key).

    What dimensional_entropy / slice-conditional measures consume — e.g.
    net_amount grouped by cost_center. Empty slice keys become the ``""`` group
    (preserves the null-slice), non-numeric values are skipped.
    """
    rows = conn.execute(
        "SELECT row_json FROM raw_values WHERE strategy=? AND source=?",
        (strategy, source),
    ).fetchall()
    out: dict[str, list[float]] = {}
    for (row_json,) in rows:
        rec = json.loads(row_json)
        raw = rec.get(value_col)
        if raw in (None, ""):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        out.setdefault(rec.get(slice_col) or "", []).append(val)
    return out
