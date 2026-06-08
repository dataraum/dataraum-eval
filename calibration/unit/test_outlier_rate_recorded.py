"""Tier-2 recorded finding for outlier_rate (DAT-442).

RECORDS, in milliseconds against the frozen fixture, why outlier_rate cannot be
fixed by the planned "drop the piecewise boost, keep the shape/CV machinery" move:
the absolute single-column IQR/z-score measure has NO setting that separates an
injected outlier burst from clean financial heavy tails. This is the same wall
that CUT temporal_drift and slice_variance — a third time.

The evidence (all self-contained in entropy_inputs.sqlite):

1. **Shape adaptation ON absorbs the injection.** Replicating outliers.py's method
   (exclude structural zeros when >30% mass at 0, then log-IQR on the positive
   tail where a right-skewed column is ~normal) on journal_lines.credit — which
   carries a 5%-at-10x injection in detection-v1 — gives clean ≈ injected ≈ 0.003.
   A 10x multiplier is only +log(10)≈2.3 in log space, inside the natural spread,
   so the log-IQR that tames clean tails also tames the injection. No separation.

2. **Shape adaptation OFF manufactures a huge clean false-positive surface.**
   Linear IQR on journal_lines.net_amount (a clean, symmetric, signed heavy tail —
   no injection) flags ~26% of values as outliers. And the profiler's OWN run
   confirms the scale: dozens of columns carry raw iqr_outlier_ratio >= 0.20 on a
   single detection-v1 run. Under identity scoring without shape adaptation those
   all read "critical" — false positives on legitimate financial structure.

So (1) and (2) are the two horns: any IQR setting that suppresses the clean surface
also blinds the detector to the injection, and vice versa. The old baseline's
"credit -> 1.000" was the piecewise map inflating a linear-IQR artifact, balanced
against the shape machinery — not a grounded measurement. Disposition (CUT vs.
redesign as distributional surprise D_KL(observed||reference) with an expected-
variation reference, cf. DAT-445) is a design decision, tracked separately; this
test just freezes the finding so it is not rediscovered by another 10-min run.
"""

from __future__ import annotations

import numpy as np
from scipy import stats  # type: ignore[import-untyped]

from calibration.unit.fixture import column_values, load_fixture

_ZERO_INFLATED = 0.30  # matches outliers.py _ZERO_INFLATED_THRESHOLD
_SKEW = 1.5  # matches outliers.py _SKEWNESS_THRESHOLD


def _shape_aware_outlier_ratio(values: list[float]) -> float:
    """The outlier ratio outliers.py KEEPS after shape adaptation (no score map).

    Zero-inflated (mutex debit/credit) -> exclude structural zeros; right-skewed
    -> log-IQR on the positive tail; otherwise linear IQR. Returns the fraction of
    values outside the 1.5*IQR fences — what identity scoring would emit directly.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 10:
        return 0.0
    zero_frac = float(np.mean(arr == 0.0))
    work = arr[arr != 0.0] if zero_frac > _ZERO_INFLATED else arr
    if work.size < 10:
        return 0.0
    pos = work[work > 0]
    skew = float(stats.skew(work))
    if (skew > _SKEW or zero_frac > _ZERO_INFLATED) and pos.size >= 10:
        logv = np.log(pos)
        q1, q3 = np.percentile(logv, [25, 75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        return float(np.mean((logv < lo) | (logv > hi)))
    q1, q3 = np.percentile(work, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return float(np.mean((work < lo) | (work > hi)))


def _linear_iqr_ratio(values: list[float]) -> float:
    """Plain linear IQR outlier fraction — what identity scoring emits with NO shape
    adaptation. Surfaces the clean heavy-tail false-positive surface."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 10:
        return 0.0
    q1, q3 = np.percentile(arr, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return float(np.mean((arr < lo) | (arr > hi)))


def test_shape_aware_iqr_absorbs_the_injection() -> None:
    """Horn 1: with shape adaptation ON the 5%-at-10x credit injection does not
    separate from clean — both ~0.003 (log-IQR swallows the burst)."""
    conn = load_fixture()
    clean = _shape_aware_outlier_ratio(column_values(conn, "clean", "journal_lines", "credit"))
    injected = _shape_aware_outlier_ratio(
        column_values(conn, "detection-v1", "journal_lines", "credit")
    )
    conn.close()
    # The recorded finding: NO separation (the opposite of recall). Both tiny.
    assert clean < 0.02 and injected < 0.02, f"clean={clean:.4f} injected={injected:.4f}"
    assert abs(injected - clean) < 0.02, (
        f"unexpected separation appeared: clean={clean:.4f} injected={injected:.4f} "
        f"(delta={injected - clean:+.4f}) — re-examine the outlier_rate disposition"
    )


def test_shape_off_manufactures_clean_false_positives() -> None:
    """Horn 2: with shape adaptation OFF, a clean signed heavy tail
    (journal_lines.net_amount, no injection) reads ~26% outliers — identity scoring
    without shape adaptation would flag legitimate financial structure as critical."""
    conn = load_fixture()
    net_amount = _linear_iqr_ratio(column_values(conn, "detection-v1", "journal_lines", "net_amount"))
    conn.close()
    assert net_amount > 0.20, (
        f"net_amount linear-IQR false-positive surface {net_amount:.4f} — expected the "
        f"large clean heavy-tail surface that motivates KEEPING shape adaptation"
    )


def test_profiler_run_confirms_the_false_positive_surface() -> None:
    """The profiler's OWN single-run numbers confirm the surface at scale: many
    columns carry raw iqr_outlier_ratio >= 0.20 on clean-ish financial data — the
    natural long tail, not data quality. Absolute IQR cannot tell them apart."""
    conn = load_fixture()
    rows = conn.execute(
        "SELECT iqr_outlier_ratio FROM statistical_quality_metrics "
        "WHERE iqr_outlier_ratio IS NOT NULL"
    ).fetchall()
    conn.close()
    high = sum(1 for (r,) in rows if r is not None and float(r) >= 0.20)
    assert high > 20, (
        f"only {high} columns with raw IQR ratio >= 0.20 — expected a broad surface "
        f"(the financial heavy-tail cluster at 0.25-0.285)"
    )
