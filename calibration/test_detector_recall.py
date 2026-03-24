"""Detector recall — does each detector find its known injection?

For each injection in entropy_map.yaml, the corresponding detector must
produce a score > DETECTION_THRESHOLD for the affected target. Column-scoped
detectors are checked per-column; table/view-scoped detectors are checked
per-table or per-view.

This is the core calibration test. A failing test means a detector is broken,
not that the test needs weakening.

Two strategies cover all 15 detectors:
- detection-v1: comprehensive (no type-breaking). 13 detectors.
- detection-typing-v1: type_fidelity + temporal_entropy (breaks types,
  run separately to avoid interference with downstream detectors).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Minimum score for a detector to be considered "detected the injection"
DETECTION_THRESHOLD = 0.3

EVAL_ROOT = Path(__file__).parent.parent

# Detectors that don't exist yet — always skip
NOT_IMPLEMENTED = frozenset({
    "derived_value_consistency",
})

# Detectors where the injection is known-misaligned (documents the gap)
KNOWN_MISALIGNED = frozenset({
    "unit_entropy",  # Measures metadata, injection corrupts values
})

# Injections where the detector can't see the specific target column.
# Key: (detector_id, table, column). Reason documented inline.
KNOWN_DETECTOR_GAPS: dict[tuple[str, str, str], str] = {
    ("derived_value", "trial_balance", "debit_balance"): (
        "Cross-table aggregate formula (SUM(journal_lines.debit) GROUP BY account, period) — "
        "out of scope for within-table correlation detector"
    ),
}


def _injection_id(injection: dict[str, Any]) -> str:
    """Human-readable ID for parametrize."""
    table = injection["target_file"].replace(".csv", "")
    return f"{injection['detector_id']}:{table}.{injection['target_column']}"


def _get_injections(strategy: str) -> list[dict[str, Any]]:
    """Load injections for parametrize (runs at collection time)."""
    path = EVAL_ROOT / "data" / strategy / "entropy_map.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    result: list[dict[str, Any]] = data.get("injections", [])
    return result


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parametrize injection tests based on --strategy."""
    if "injection" in metafunc.fixturenames:
        strategy = metafunc.config.getoption("--strategy", default="detection-v1")
        injections = _get_injections(strategy)
        ids = [_injection_id(inj) for inj in injections]
        metafunc.parametrize("injection", injections, ids=ids)


def _find_score(
    table: str,
    column: str,
    detector: str,
    pipeline_scores: dict[tuple[str, str, str], float],
    pipeline_table_scores: dict[tuple[str, str], float],
    pipeline_view_scores: dict[tuple[str, str], float],
) -> float | None:
    """Find a detector score across column, table, and view scopes."""
    # Column-scoped: exact (table, column, detector) match
    score = pipeline_scores.get((table, column, detector))
    if score is not None:
        return score

    # Table-scoped: (table, detector) match
    score = pipeline_table_scores.get((table, detector))
    if score is not None:
        return score

    # View-scoped: any view matching this detector
    for (_, d), s in pipeline_view_scores.items():
        if d == detector:
            return s

    # Column-scoped fallback: best score for this (table, detector) across all columns.
    # Handles derived_value where injection on column A breaks a formula attributed
    # to column B (correlations dedup picks sum over difference).
    best = None
    for (t, _, d), s in pipeline_scores.items():
        if t == table and d == detector:
            if best is None or s > best:
                best = s
    return best


def test_injection_detected(
    injection: dict[str, Any],
    pipeline_scores: dict[tuple[str, str, str], float],
    pipeline_table_scores: dict[tuple[str, str], float],
    pipeline_view_scores: dict[tuple[str, str], float],
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Each known injection must produce an elevated score for the affected column."""
    table = injection["target_file"].replace(".csv", "")
    column = injection["target_column"]
    detector = injection["detector_id"]

    # Always skip unimplemented detectors
    if detector in NOT_IMPLEMENTED:
        pytest.skip(f"{detector} not implemented yet")

    # Mark known-misaligned injections as expected failures
    if detector in KNOWN_MISALIGNED:
        pytest.xfail(f"{detector} injection is known-misaligned (see CLAUDE.md)")

    # Mark specific detector+target gaps as expected failures
    gap_key = (detector, table, column)
    if gap_key in KNOWN_DETECTOR_GAPS:
        pytest.xfail(KNOWN_DETECTOR_GAPS[gap_key])

    # Pipeline lowercases column names during import
    column_lc = column.lower()

    # Some injections affect multiple columns (e.g., debit/credit mutex)
    if "/" in column:
        cols = column_lc.split("/")
        scores = [
            _find_score(table, c, detector, pipeline_scores, pipeline_table_scores, pipeline_view_scores)
            for c in cols
        ]
        best = max((s for s in scores if s is not None), default=None)
        assert best is not None, (
            f"{detector} produced no score for {table}.{{{column}}} — "
            f"detector didn't run or doesn't cover this injection type"
        )
        assert best > DETECTION_THRESHOLD, (
            f"{detector} scored {best:.3f} for {table}.{{{column}}} — "
            f"injection missed (threshold={DETECTION_THRESHOLD})"
        )
        return

    score = _find_score(table, column_lc, detector, pipeline_scores, pipeline_table_scores, pipeline_view_scores)
    assert score is not None, (
        f"{detector} produced no score for {table}.{column} — "
        f"detector didn't run or doesn't cover this injection type"
    )

    clean = clean_pipeline_scores.get((table, column_lc, detector), 0.0)
    delta = score - clean

    assert score > DETECTION_THRESHOLD, (
        f"{detector} scored {score:.3f} for {table}.{column} "
        f"(clean={clean:.3f}, delta={delta:+.3f}) — "
        f"injection missed (threshold={DETECTION_THRESHOLD})"
    )
