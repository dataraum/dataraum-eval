"""Fix calibration — does applying a fix reduce the detector score?

For each fix spec, the detector must produce a lower score after the fix
is applied. This proves the complete fix system works end-to-end:
detector fires → fix applied → score drops.

Phase 1: accept_finding fixes (config writes, re-measure at gate)
Phase 2: metadata fixes (direct DB update, re-measure at gate)
Phase 3: config fixes requiring phase re-run
"""

from __future__ import annotations

import pytest

from calibration.fix_specs import ZONE1_FIX_SPECS, ZONE2_FIX_SPECS, FixSpec

# Table-scoped detectors — score lookup uses (table, detector) not (table, column, detector)
TABLE_SCOPED_DETECTORS = frozenset({"dimensional_entropy", "column_quality"})


def _get_fix_specs(strategy: str) -> list[FixSpec]:
    """Return fix specs matching the strategy."""
    if "zone2" in strategy:
        return ZONE2_FIX_SPECS
    return ZONE1_FIX_SPECS


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parametrize fix tests from fix specs."""
    if "fix_spec" in metafunc.fixturenames:
        strategy = metafunc.config.getoption("--strategy", default="zone1-detection-v1")
        specs = _get_fix_specs(strategy)
        ids = [spec.test_id for spec in specs]
        metafunc.parametrize("fix_spec", specs, ids=ids)


def _lookup_score(
    fix_spec: FixSpec,
    column_scores: dict[tuple[str, str, str], float],
    table_scores: dict[tuple[str, str], float],
) -> float | None:
    """Find score for a fix spec across column and table scopes."""
    if fix_spec.detector_id in TABLE_SCOPED_DETECTORS:
        return table_scores.get((fix_spec.table, fix_spec.detector_id))
    return column_scores.get((fix_spec.table, fix_spec.column, fix_spec.detector_id))


def test_fix_reduces_score(
    fix_spec: FixSpec,
    pipeline_scores: dict[tuple[str, str, str], float],
    pipeline_table_scores: dict[tuple[str, str], float],
    post_fix_scores: dict[tuple[str, str, str], float],
    post_fix_table_scores: dict[tuple[str, str], float],
) -> None:
    """Applying a fix must reduce the detector score for the affected column.

    Exception: accept_finding keeps scores honest — the score stays unchanged
    and the gate passes via contract overrule (accepted evidence flag).
    """
    if fix_spec.xfail_reason:
        pytest.xfail(fix_spec.xfail_reason)

    pre = _lookup_score(fix_spec, pipeline_scores, pipeline_table_scores)
    assert pre is not None, (
        f"No pre-fix score for {fix_spec.test_id} — "
        f"detector didn't run or doesn't cover this target"
    )

    post = _lookup_score(fix_spec, post_fix_scores, post_fix_table_scores)
    assert post is not None, (
        f"No post-fix score for {fix_spec.test_id} — "
        f"re-run may have failed"
    )

    if fix_spec.is_acceptance:
        # accept_finding keeps scores honest — contract overrule handles the gate.
        # Score should be approximately unchanged (re-measurement may cause minor drift).
        assert abs(post - pre) < 0.05, (
            f"{fix_spec.test_id}: score changed unexpectedly after accept_finding — "
            f"pre={pre:.3f} post={post:.3f} (expected honest score, ~unchanged)"
        )
        return

    assert post < pre, (
        f"{fix_spec.test_id}: score did not drop — "
        f"pre={pre:.3f} post={post:.3f} (expected post < pre)"
    )

    assert post <= fix_spec.expected_max_score, (
        f"{fix_spec.test_id}: score {post:.3f} above floor "
        f"{fix_spec.expected_max_score} — fix may be partial"
    )
