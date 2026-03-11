"""Detector precision — no false alarms on clean data.

On clean data (no injections), all detector scores should be low.
A high score on clean data means the detector is producing false positives.
"""

from __future__ import annotations

# Maximum score on clean data before it's considered a false alarm
FALSE_ALARM_THRESHOLD = 0.2


def test_no_false_alarms(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """No column should have a score above threshold on clean data."""
    false_alarms = [
        (table, column, detector, score)
        for (table, column, detector), score in clean_pipeline_scores.items()
        if score > FALSE_ALARM_THRESHOLD
    ]

    if false_alarms:
        lines = [f"  {d}: {t}.{c} = {s:.3f}" for t, c, d, s in false_alarms]
        msg = f"{len(false_alarms)} false alarms on clean data:\n" + "\n".join(lines)
        assert False, msg


def test_clean_average_below_threshold(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Average score across all columns on clean data should be very low."""
    if not clean_pipeline_scores:
        return  # No scores to check

    avg = sum(clean_pipeline_scores.values()) / len(clean_pipeline_scores)
    assert avg < 0.15, f"Average clean score {avg:.3f} too high — detectors are noisy"
