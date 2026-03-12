"""Detector recall — does each detector find its known injection?

For each injection in entropy_map.yaml, the corresponding detector must
produce a score > DETECTION_THRESHOLD for the affected column. If it doesn't,
the detector has a bug.

This is the core calibration test. A failing test means a detector is broken,
not that the test needs weakening.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Minimum score for a detector to be considered "detected the injection"
DETECTION_THRESHOLD = 0.3

EVAL_ROOT = Path(__file__).parent.parent


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
