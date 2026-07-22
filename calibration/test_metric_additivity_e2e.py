"""Metric additivity oracle — the DAT-718 drill matrix on a real finance run.

Grades the engine's persisted ``metric_additivity`` verdicts (DAT-716) against
the hand-authored ground truth in ``metadata_truth.yaml`` — the first
agent-metadata oracle (DAT-680 P1). The matrix it exercises end-to-end:

* ``SUM(flow)``          → additive on both axes            (revenue)
* ``SUM(stock)``         → time-stripped, categorical-additive (current_assets/liabilities, measure verdicts)
* ``COUNT`` event fact   → additive on both axes            (transaction_count)
* ``COUNT(DISTINCT)``    → non-additive                     (active_accounts / account)
* ``AVG``                → non-additive                     (average_transaction_value)
* ratio                  → non-additive on every axis       (current_ratio)

Two tiers (``metadata_truth`` ``determinism``), the anti-Goodhart split:

* **function_symmetry** — AVG / COUNT(DISTINCT) / ratio never reconcile on any
  axis, independent of any upstream label. **HARD-asserted**: a mismatch is a real
  defect in the DAT-716 classifier or its persistence, and no stock/flow verdict
  can game it (the no-deterministic-override rule is respected — we hard-assert
  only what is label-invariant).
* **label_dependent** — SUM(flow)→additive, SUM(stock)→time-stripped, COUNT→
  additive-on-event-grain: the verdict also needs a correct stock/flow verdict
  (the pooled temporal_behavior detector, DAT-685) or grain (DAT-716). Reported as
  a **diagnostic** (xfail, strict=False semantics), never a hard build-break — the
  upstream detector is graded in its own P1 lane, not re-graded here.

Grounding recall itself is the ``/smoke`` lane, not the oracle: this test SKIPS
when the new activity metrics produced no verdict at all, rather than passing
vacuously. Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import (
    expected_additivity,
    read_metric_additivity,
)
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")

# The DAT-718 cells whose total absence means grounding never reached them (the
# /smoke concern) rather than an oracle failure — if NONE produced a verdict, we
# skip instead of vacuous-passing on an empty result set.
_NEW_MATRIX_TARGETS = {
    ("metric", "average_transaction_value"),
    ("metric", "active_accounts"),
    ("metric", "transaction_count"),
}


def _fields(spec_or_verdict: object) -> tuple[Any, Any, Any, Any]:
    """The four graded fields as a comparable tuple."""
    if isinstance(spec_or_verdict, dict):
        return (
            spec_or_verdict["categorical_additive"],
            spec_or_verdict["time_additive"],
            spec_or_verdict.get("categorical_reason"),
            spec_or_verdict.get("time_reason"),
        )
    v = spec_or_verdict
    return (v.categorical_additive, v.time_additive, v.categorical_reason, v.time_reason)  # type: ignore[attr-defined]


@pytest.mark.llm
def test_metric_additivity_matrix_oracle(
    metadata_truth: dict[str, Any], strategy_name: str
) -> None:
    """The persisted additivity verdicts match the matrix ground truth.

    Grades ONLY the strategy under test against its own truth (DAT-797).
    """
    require_pipeline_run(strategy_name)

    with workspace_session() as session:
        actual = read_metric_additivity(session)

    expected = expected_additivity(metadata_truth)

    if not (actual.keys() & _NEW_MATRIX_TARGETS):
        pytest.skip(
            "none of the DAT-718 activity metrics produced an additivity verdict — "
            "metric grounding didn't reach them (the /smoke grounding lane, not the "
            f"oracle). Present verdicts: {sorted(actual)}"
        )

    hard_fail: list[str] = []
    soft_mismatch: list[str] = []
    soft_missing: list[str] = []
    matrix: list[str] = []
    grounded = 0
    for (kind, key), spec in expected.items():
        got = actual.get((kind, key))
        determinism = spec.get("determinism")
        tier = "HARD" if determinism == "function_symmetry" else "soft"
        if got is None:
            # Not grounded. For function_symmetry targets that DID exist we assert;
            # a missing one is a grounding-recall gap (smoke), reported not failed.
            soft_missing.append(f"  {kind}:{key} — no verdict (not grounded)")
            matrix.append(f"  [{tier}] {kind}:{key:<26} — not grounded")
            continue
        grounded += 1
        want, have = _fields(spec), _fields(got)
        verdict = (
            f"cat={got.categorical_additive} time={got.time_additive} "
            f"reason=({got.categorical_reason},{got.time_reason})"
        )
        if want == have:
            matrix.append(f"  [{tier}] {kind}:{key:<26} ✓ {verdict}")
            continue
        line = f"  {kind}:{key} — expected {want}, got {have}"
        matrix.append(f"  [{tier}] {kind}:{key:<26} ✗ {verdict}  (expected {want})")
        if determinism == "function_symmetry":
            hard_fail.append(line)
        else:
            soft_mismatch.append(line + "  [label/grain-dependent]")

    print(
        f"\n[additivity oracle] {grounded}/{len(expected)} targets grounded on "
        f"{strategy_name}; hard-fail={len(hard_fail)} soft-mismatch={len(soft_mismatch)} "
        f"not-grounded={len(soft_missing)}"
    )
    for line in matrix:
        print(line)

    # HARD: label-invariant verdicts (AVG / COUNT(DISTINCT) / ratio) must be exact.
    assert not hard_fail, (
        "function-symmetry additivity verdicts are wrong — a label-independent "
        "defect in the DAT-716 classifier or its persistence:\n" + "\n".join(hard_fail)
    )

    # SOFT: a grounded label/grain-dependent divergence is a real signal for the
    # stock/flow (DAT-685) or grain (DAT-716) lane — surfaced as xfail, never a
    # deterministic re-grade of the upstream stock/flow / grain detector here.
    if soft_mismatch:
        pytest.xfail(
            "label/grain-dependent additivity cells diverge from ground truth — "
            "a stock/flow (DAT-685) or grain (DAT-716) labeling signal, not an "
            "oracle fail:\n" + "\n".join(soft_mismatch)
        )
