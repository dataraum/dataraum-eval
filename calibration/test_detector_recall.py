"""Detector recall — does each detector find its known injection?

For each injection in entropy_map.yaml, the corresponding detector must
produce a score > DETECTION_THRESHOLD for the affected column. If it doesn't,
the detector has a bug.

This is the core calibration test. A failing test means a detector is broken,
not that the test needs weakening.
"""

from __future__ import annotations

from typing import Any

import pytest

# Minimum score for a detector to be considered "detected the injection"
DETECTION_THRESHOLD = 0.3


def _injection_id(injection: dict[str, Any]) -> str:
    """Human-readable ID for parametrize."""
    table = injection["target_file"].replace(".csv", "")
    return f"{injection['detector_id']}:{table}.{injection['target_column']}"


def _get_injections(entropy_map_path: str = "data/medium/entropy_map.yaml") -> list[dict[str, Any]]:
    """Load injections for parametrize (runs at collection time)."""
    from pathlib import Path

    import yaml

    path = Path(__file__).parent.parent / entropy_map_path
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("injections", [])


# Parametrize at module level so each injection is a separate test
_INJECTIONS = _get_injections()


@pytest.mark.parametrize(
    "injection",
    _INJECTIONS,
    ids=[_injection_id(inj) for inj in _INJECTIONS],
)
def test_injection_detected(
    injection: dict[str, Any],
    medium_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Each known injection must produce an elevated score for the affected column."""
    table = injection["target_file"].replace(".csv", "")
    column = injection["target_column"]
    detector = injection["detector_id"]

    # Some injections affect multiple columns (e.g., debit/credit mutex)
    if "/" in column:
        # Check both columns — at least one should be detected
        cols = column.split("/")
        scores = [
            medium_pipeline_scores.get((table, c, detector))
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

    score = medium_pipeline_scores.get((table, column, detector))
    assert score is not None, (
        f"{detector} produced no score for {table}.{column} — "
        f"detector didn't run or doesn't cover this injection type"
    )
    assert score > DETECTION_THRESHOLD, (
        f"{detector} scored {score:.3f} for {table}.{column} — "
        f"injection missed (threshold={DETECTION_THRESHOLD})"
    )
