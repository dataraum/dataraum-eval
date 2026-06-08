"""TABLE 1 of the two-table model — the measurement table.

Each measurement is a PURE function over recorded column data → a value in [0, 1].
No pipeline, no docker: proven in milliseconds against the committed fixture. This
file proves the measurement VALUE; ``test_risk_rollup`` proves value → loss → band.

A measurement earns a row here only if it is *tunable entropy* a teach can close
(type, unit, relationships, nulls, derived formulas, …). Informative signals no
teach resolves (benford, outliers, drift, variance) are column context, not
measurements — they do not appear here.
"""

from __future__ import annotations

import sqlite3

from dataraum.entropy.stats import null_ratio

from calibration.unit.fixture import column_cells, load_fixture

MARGIN = 0.05


def _engine_scores(conn: sqlite3.Connection, detector_id: str, target_like: str) -> list[float]:
    """The pipeline's persisted scores for a measurement (captured as TEXT)."""
    rows = conn.execute(
        "SELECT score FROM entropy_objects WHERE detector_id=? AND target LIKE ?",
        (detector_id, target_like),
    ).fetchall()
    return [float(s) for (s,) in rows]


def test_null_ratio_is_a_pure_rate_that_reproduces_the_engine() -> None:
    """null_ratio(cells) = missing/total — reproduces the pipeline's persisted score,
    and the cost_center null injection separates injected from clean."""
    conn = load_fixture()
    clean = null_ratio(column_cells(conn, "clean", "journal_lines", "cost_center"))
    injected = null_ratio(column_cells(conn, "detection-v1", "journal_lines", "cost_center"))

    assert 0.0 <= clean <= 1.0
    assert 0.0 <= injected <= 1.0
    # ordering: the injection raises the missing fraction past clean + margin.
    assert injected > clean + MARGIN, f"injected {injected:.3f} !> clean {clean:.3f} + {MARGIN}"

    # identity vs the engine: the eval stat == the pipeline's own null_ratio measurement.
    engine = _engine_scores(conn, "null_ratio", "%journal_lines.cost_center")
    assert any(abs(injected - s) < 0.01 for s in engine), f"{injected:.3f} not in engine {engine}"
    assert any(abs(clean - s) < 0.01 for s in engine), f"{clean:.3f} not in engine {engine}"
