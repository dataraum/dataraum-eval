"""Fix calibration — does applying a fix reduce the detector score?

For each fix spec, the detector must produce a lower score after the fix
is applied. This proves the complete fix system works end-to-end:
detector fires → fix applied → score drops.

Phase 1: accept_finding fixes (config-only, quality_review re-run)
Phase 2: semantic/typing/relationship fixes (skip until implemented)
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration.fix_specs import ZONE1_FIX_SPECS, FixSpec


def _get_fix_specs() -> list[FixSpec]:
    return ZONE1_FIX_SPECS


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parametrize fix tests from fix specs."""
    if "fix_spec" in metafunc.fixturenames:
        specs = _get_fix_specs()
        ids = [spec.test_id for spec in specs]
        metafunc.parametrize("fix_spec", specs, ids=ids)


def test_fix_reduces_score(
    fix_spec: FixSpec,
    pipeline_scores: dict[tuple[str, str, str], float],
    post_fix_scores: dict[tuple[str, str, str], float],
) -> None:
    """Applying a fix must reduce the detector score for the affected column."""
    # Phase 2 specs not yet implemented
    if fix_spec.phase == 2 and not fix_spec.fix_documents:
        pytest.skip(f"Phase 2 fix not implemented: {fix_spec.action}")

    if fix_spec.xfail_reason:
        pytest.xfail(fix_spec.xfail_reason)

    key = (fix_spec.table, fix_spec.column, fix_spec.detector_id)

    pre = pipeline_scores.get(key)
    assert pre is not None, (
        f"No pre-fix score for {fix_spec.test_id} — "
        f"detector didn't run or doesn't cover this column"
    )

    post = post_fix_scores.get(key)
    assert post is not None, (
        f"No post-fix score for {fix_spec.test_id} — "
        f"re-run may have failed"
    )

    assert post < pre, (
        f"{fix_spec.test_id}: score did not drop — "
        f"pre={pre:.3f} post={post:.3f} (expected post < pre)"
    )

    assert post <= fix_spec.expected_max_score, (
        f"{fix_spec.test_id}: score {post:.3f} above floor "
        f"{fix_spec.expected_max_score} — fix may be partial"
    )
