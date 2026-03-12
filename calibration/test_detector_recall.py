"""Detector recall — does each detector find its known injection?

For each injection in entropy_map.yaml, the corresponding detector must
produce a score > DETECTION_THRESHOLD for the affected column. If it doesn't,
the detector has a bug.

This is the core calibration test. A failing test means a detector is broken,
not that the test needs weakening.

Injections targeting detectors that don't run at Zone 1 (temporal_drift,
dimensional_entropy, derived_value) or detectors that don't exist yet
(cross_table_consistency, derived_value_consistency) are skipped — they
are kept in the strategy for Zone 2+ testing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Minimum score for a detector to be considered "detected the injection"
DETECTION_THRESHOLD = 0.3

EVAL_ROOT = Path(__file__).parent.parent

# Detectors that don't run at Zone 1 (need Zone 2+ analyses or don't exist)
NOT_AT_ZONE_1 = frozenset({
    "temporal_drift",       # Zone 2: needs DRIFT_SUMMARIES
    "dimensional_entropy",  # Zone 2: needs SLICE_VARIANCE
    "derived_value",        # Zone 2: needs CORRELATION
    "column_quality",       # Zone 2: needs COLUMN_QUALITY_REPORTS
    "dimension_coverage",   # Zone 2: needs ENRICHED_VIEW
    "cross_table_consistency",    # Doesn't exist yet
    "derived_value_consistency",  # Doesn't exist yet
})

# Detectors where the injection is known-misaligned (documents the gap)
KNOWN_MISALIGNED = frozenset({
    "unit_entropy",  # Measures metadata, injection corrupts values
})


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
    return data.get("injections", [])


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parametrize injection tests based on --strategy."""
    if "injection" in metafunc.fixturenames:
        strategy = metafunc.config.getoption("--strategy", default="zone1-detection-v1")
        injections = _get_injections(strategy)
        ids = [_injection_id(inj) for inj in injections]
        metafunc.parametrize("injection", injections, ids=ids)


def test_injection_detected(
    injection: dict[str, Any],
    pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Each known injection must produce an elevated score for the affected column."""
    table = injection["target_file"].replace(".csv", "")
    column = injection["target_column"]
    detector = injection["detector_id"]

    # Skip detectors that don't run at Zone 1
    if detector in NOT_AT_ZONE_1:
        pytest.skip(f"{detector} not available at Zone 1")

    # Mark known-misaligned injections as expected failures
    if detector in KNOWN_MISALIGNED:
        pytest.xfail(f"{detector} injection is known-misaligned (see CLAUDE.md)")

    # Pipeline lowercases column names during import
    column_lc = column.lower()

    # Some injections affect multiple columns (e.g., debit/credit mutex)
    if "/" in column:
        # Check both columns — at least one should be detected
        cols = column_lc.split("/")
        scores = [
            pipeline_scores.get((table, c, detector))
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

    score = pipeline_scores.get((table, column_lc, detector))
    assert score is not None, (
        f"{detector} produced no score for {table}.{column} — "
        f"detector didn't run or doesn't cover this injection type"
    )
    assert score > DETECTION_THRESHOLD, (
        f"{detector} scored {score:.3f} for {table}.{column} — "
        f"injection missed (threshold={DETECTION_THRESHOLD})"
    )
