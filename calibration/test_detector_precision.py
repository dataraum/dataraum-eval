"""Detector precision — behavior on clean data, guarded by MEASURED bands.

On clean data (no injections), detector scores reflect baseline data
characteristics, not problems — and a clean emission is a DISTRIBUTION, not a
point: LLM annotation coverage and confidence vary run to run (the A4 seed
sweep measured 145-208 column emissions across four seeds of the same clean
strategy). The guard is therefore a measured band per key
(``calibration/clean_bands.yaml``, built by ``scripts/build_clean_bands.py``
from the sweep dumps), at every grain the rollup scores — column, table,
relationship. A score above its band's max (plus tolerance) is a regression;
a high score with no band is a NEW emission to triage. Scores at or below the
noise floor are uninteresting at any grain.

Regenerate bands only by resweeping (the driver in scripts/probes/ is recreated
per sweep) and rebuilding — never by hand-editing a band to make a run pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from calibration.conftest import DetectorScores

EVAL_ROOT = Path(__file__).parent.parent
BANDS_PATH = EVAL_ROOT / "calibration" / "clean_bands.yaml"

# Scores at or below this are uninteresting — don't track them
NOISE_FLOOR = 0.15

# Per-detector floors where the default sits INSIDE the detector's natural
# clean emission band. business_meaning hedges at 0.15-0.20 on a rotating
# subset of legitimately-named clean columns (LLM confidence wobble — observed
# across three batches: date/reference/amount entries shuffle every run, all
# <= 0.2); the recall suite already classifies it LLM-nondeterministic. Above
# 0.2 on clean IS a precision regression and stays tracked.
NOISE_FLOOR_BY_DETECTOR = {"business_meaning": 0.2}

# Band max + this much is a regression (sampling slack atop a 4-seed band).
BAND_TOLERANCE = 0.05


def _floor_for(detector: str) -> float:
    return NOISE_FLOOR_BY_DETECTOR.get(detector, NOISE_FLOOR)


def _load_bands() -> dict[str, dict[str, dict[str, Any]]]:
    if not BANDS_PATH.exists():
        pytest.skip(
            f"No measured bands at {BANDS_PATH} — run a clean seed sweep and "
            "scripts/build_clean_bands.py."
        )
    data = yaml.safe_load(BANDS_PATH.read_text()) or {}
    result: dict[str, dict[str, dict[str, Any]]] = data.get("bands", {})
    return result


def _scored_keys(scores: DetectorScores) -> dict[str, dict[str, tuple[str, float]]]:
    """Per grain: band key -> (detector, score), matching the sweep dump's keys."""
    return {
        "column": {f"{t}.{c}:{d}": (d, s) for (t, c, d), s in scores.column.items()},
        "table": {f"{t}:{d}": (d, s) for (t, d), s in scores.table.items()},
        "relationship": {f"{t}.{c}:{d}": (d, s) for (t, c, d), s in scores.relationship.items()},
    }


def test_clean_scores_within_measured_bands(
    clean_detector_scores: DetectorScores,
) -> None:
    """Every clean score above its floor sits within its measured band (+tolerance).

    Covers ALL scored grains — the old captured baseline guarded column grain
    only, leaving dimension_coverage (table) and the relationship scalars
    unguarded (B2 finding).
    """
    bands = _load_bands()
    regressions: list[str] = []
    new_high: list[str] = []

    for grain, keyed in _scored_keys(clean_detector_scores).items():
        grain_bands = bands.get(grain, {})
        for key, (detector, score) in sorted(keyed.items()):
            if score <= _floor_for(detector):
                continue
            band = grain_bands.get(key)
            if band is None:
                new_high.append(f"  [{grain}] {key}: {score:.3f} (NEW — no band)")
            elif score > float(band["max"]) + BAND_TOLERANCE:
                regressions.append(
                    f"  [{grain}] {key}: {score:.3f} > band [{band['min']:.3f}, "
                    f"{band['max']:.3f}] + {BAND_TOLERANCE} (seen {band['seen']}x)"
                )

    lines = []
    if regressions:
        lines.append(f"{len(regressions)} regressions above measured bands:")
        lines.extend(regressions)
    if new_high:
        lines.append(f"{len(new_high)} new high scores with no measured band:")
        lines.extend(new_high)
    if lines:
        lines.append("")
        lines.append(
            "If a detector or spec change makes these expected, resweep (clean at "
            ">= 2 seeds) and rebuild: uv run python scripts/build_clean_bands.py. "
            "Never hand-edit a band."
        )
        raise AssertionError("\n".join(lines))


def test_clean_average_below_threshold(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Average column score across clean data should be low.

    This catches systematic drift where many detectors start scoring higher.
    """
    if not clean_pipeline_scores:
        return

    avg = sum(clean_pipeline_scores.values()) / len(clean_pipeline_scores)
    assert avg < 0.15, f"Average clean score {avg:.3f} too high — detectors are noisy"
