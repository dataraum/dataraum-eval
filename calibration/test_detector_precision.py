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

# Per-detector floors where the default sits INSIDE the detector's natural
# clean emission band. business_meaning hedges at 0.15-0.20 on a rotating
# subset of legitimately-named clean columns (LLM confidence wobble — observed
# across three batches: date/reference/amount entries shuffle every run, all
# <= 0.2); the recall suite already classifies it LLM-nondeterministic. Above
# 0.2 on clean IS a precision regression and stays tracked. The statistical
# treatment of LLM-variance baselines (captured baseline vs generative seeds)
# is a regroup/S2 item — this floor is the observed band, not a tuned knob.
NOISE_FLOOR_BY_DETECTOR = {"business_meaning": 0.2}


def _floor_for(detector: str) -> float:
    return NOISE_FLOOR_BY_DETECTOR.get(detector, NOISE_FLOOR)


def _load_baseline() -> dict[str, float]:
    """Load known clean baseline scores."""
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH) as f:
        data = yaml.safe_load(f) or {}
    result: dict[str, float] = data.get("scores", {})
    return result


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
        pytest.skip(f"No baseline existed. Generated {BASELINE_PATH}. Review and re-run.")

    tolerance = 0.05
    regressions = []
    new_high_scores = []

    for (table, column, detector), score in sorted(clean_pipeline_scores.items()):
        key = _score_key(table, column, detector)
        if score <= _floor_for(detector):
            continue

        if key in baseline:
            expected = baseline[key]
            if score > expected + tolerance:
                regressions.append(
                    f"  {key}: {score:.3f} (was {expected:.3f}, delta +{score - expected:.3f})"
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
            "If these are expected, regenerate the baseline: delete "
            "calibration/clean_baseline.yaml and re-run this test (it "
            "rewrites the file from the current clean scores), then review "
            "the diff."
        )
        raise AssertionError("\n".join(lines))


def test_clean_average_below_threshold(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Average score across all columns on clean data should be low.

    This catches systematic drift where many detectors start scoring higher.
    """
    if not clean_pipeline_scores:
        return

    avg = sum(clean_pipeline_scores.values()) / len(clean_pipeline_scores)
    assert avg < 0.15, f"Average clean score {avg:.3f} too high — detectors are noisy"


def _write_baseline(
    scores: dict[tuple[str, str, str], float],
) -> None:
    """Write clean baseline YAML file."""
    entries: dict[str, float] = {}
    for (table, column, detector), score in sorted(scores.items()):
        if score > _floor_for(detector):
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
