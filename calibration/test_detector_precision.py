"""Detector precision — behavior on clean data.

On clean data (no injections), detector scores reflect baseline data
characteristics, not problems. This test establishes the clean baseline
and catches regressions where detectors start scoring higher than expected.

Scores above threshold on clean data aren't necessarily "false alarms" —
financial data naturally has outliers, non-Benford distributions, and
nullable columns. The test distinguishes between:
- Known baseline scores (expected, documented)
- Unexpected high scores (potential detector regressions)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

EVAL_ROOT = Path(__file__).parent.parent
BASELINE_PATH = EVAL_ROOT / "calibration" / "clean_baseline.yaml"

# Scores at or below this are uninteresting — don't track them
NOISE_FLOOR = 0.15


def _load_baseline() -> dict[str, float]:
    """Load known clean baseline scores."""
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data.get("scores", {})


def _score_key(table: str, column: str, detector: str) -> str:
    """Canonical key for baseline YAML."""
    return f"{detector}:{table}.{column}"


def test_clean_scores_match_baseline(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Scores on clean data should match the known baseline within tolerance.

    If no baseline exists yet, this test generates one and skips.
    Unexpected new high scores or large deviations from baseline fail the test.
    """
    baseline = _load_baseline()

    if not baseline:
        # First run — generate baseline
        _write_baseline(clean_pipeline_scores)
        pytest.skip(
            f"No baseline existed. Generated {BASELINE_PATH}. "
            "Review and re-run."
        )

    tolerance = 0.05
    regressions = []
    new_high_scores = []

    for (table, column, detector), score in sorted(clean_pipeline_scores.items()):
        key = _score_key(table, column, detector)
        if score <= NOISE_FLOOR:
            continue

        if key in baseline:
            expected = baseline[key]
            if score > expected + tolerance:
                regressions.append(
                    f"  {key}: {score:.3f} (was {expected:.3f}, "
                    f"delta +{score - expected:.3f})"
                )
        else:
            new_high_scores.append(f"  {key}: {score:.3f} (NEW)")

    lines = []
    if regressions:
        lines.append(f"{len(regressions)} regressions (score increased):")
        lines.extend(regressions)
    if new_high_scores:
        lines.append(f"{len(new_high_scores)} new high scores:")
        lines.extend(new_high_scores)

    if lines:
        lines.append("")
        lines.append(
            "If these are expected, regenerate baseline: "
            "pytest calibration/test_detector_precision.py "
            "--regen-baseline"
        )
        assert False, "\n".join(lines)


def test_clean_average_below_threshold(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Average score across all columns on clean data should be low.

    This catches systematic drift where many detectors start scoring higher.
    """
    if not clean_pipeline_scores:
        return

    avg = sum(clean_pipeline_scores.values()) / len(clean_pipeline_scores)
    assert avg < 0.15, (
        f"Average clean score {avg:.3f} too high — detectors are noisy"
    )


def _write_baseline(
    scores: dict[tuple[str, str, str], float],
) -> None:
    """Write clean baseline YAML file."""
    entries: dict[str, float] = {}
    for (table, column, detector), score in sorted(scores.items()):
        if score > NOISE_FLOOR:
            key = _score_key(table, column, detector)
            entries[key] = round(score, 3)

    content = {
        "description": (
            "Clean data baseline scores. Scores above noise floor (0.15) "
            "are tracked here. Regenerate after detector changes."
        ),
        "scores": entries,
    }

    with open(BASELINE_PATH, "w") as f:
        yaml.dump(content, f, default_flow_style=False, sort_keys=True)
