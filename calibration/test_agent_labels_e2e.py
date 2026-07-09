"""Agent-label accuracy vs metadata_truth.yaml (DAT-680 P1, DAT-685).

Grades the stock/flow surface (`column_concepts.temporal_behavior`) — the label
the additivity oracle's `label_dependent` cells rest on. Three tiers, matched to
what is actually determinable (DAT-720 taught us the hard way that hard-asserting
an LLM-variable label is Goodhart):

* **witness liveness (HARD)** — the data-grounded structural reconciliation
  witness (DAT-491) must fire on ≥1 column. 0/N is the inert-safeguard signature
  DAT-536 introduced and DAT-720 restored.
* **structural correctness (HARD)** — for every measure that DID reconcile against
  an event fact, its pattern must map to the true stock/flow (`per_period`→flow,
  `cumulative`→stock). This is the DATA verdict — deterministic where it fires, so
  a mismatch is a real defect, not variance.
* **resolved-label accuracy (SOFT)** — the pooled `temporal_behavior` per column.
  A fact with no finer event fact to reconcile against (invoices/payments/…) is
  name-only and LLM-variable, and a structurally-contested label (trial_balance)
  resolves to the majority name pending teach-closure. So this is reported +
  xfail'd, never a hard build-break — no truth patch, no deterministic override.

Tier-3 (docker + Temporal + LLM): marked `llm`.
"""

from __future__ import annotations

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import (
    load_truth,
    read_structural_patterns,
    read_structural_witness_fired,
    read_temporal_behavior,
)
from calibration.tools._runs import workspace_session

_STRATEGY = "clean"

# Reconciliation pattern → the stock/flow behaviour it proves (DAT-491 vocab).
_PATTERN_TO_BEHAVIOR = {"per_period": "additive", "cumulative": "point_in_time"}


def _activate_or_skip() -> None:
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {_STRATEGY!r}; run "
            f"`python -m calibration.run -s {_STRATEGY}` first"
        )
    runner_mod.activate_workspace(_STRATEGY)


@pytest.mark.llm
def test_structural_stockflow_witness_is_live() -> None:
    """The data-grounded stock/flow witness must fire on ≥1 column (DAT-720).

    A 0/N is the inert-safeguard signature: DAT-536 silently disabled the DAT-491
    structural reconciliation witness (a fact's joined event date was dropped from
    lineage), so stock/flow fell back to name-only and nothing warned. This guard
    makes that fail loudly instead of hiding behind name-luck.
    """
    _activate_or_skip()
    with workspace_session() as session:
        fired, total = read_structural_witness_fired(session)

    if total == 0:
        pytest.skip("no temporal_behavior objects — stock/flow detection didn't run")

    print(f"\n[stock/flow witness] structural reconciliation fired on {fired}/{total} columns")
    assert fired > 0, (
        f"structural stock/flow witness fired on 0/{total} columns — the DAT-491 "
        "data-grounded witness is INERT; stock/flow is decided by names alone "
        "(the DAT-720 regression). No aggregation lineage reconciled any measure."
    )


@pytest.mark.llm
def test_structural_reconciliation_matches_truth() -> None:
    """Every measure that reconciled carries the right pattern for its behaviour.

    This is the HARD data-grounded check: `per_period`⇒flow, `cumulative`⇒stock. A
    measure whose ground-truth behaviour is a flow but reconciles `cumulative` (or
    vice-versa) is a real defect in the reconciliation, not LLM variance. Measures
    that didn't reconcile are absent here (name-only → the soft test below).
    """
    _activate_or_skip()
    with workspace_session() as session:
        patterns = read_structural_patterns(session)

    truth: dict[str, str] = load_truth().get("stock_flow") or {}
    graded = {col: pat for col, pat in patterns.items() if col in truth}
    if not graded:
        pytest.skip("no measure reconciled against an event fact — nothing to grade")

    mismatches: list[str] = []
    for col, pattern in sorted(graded.items()):
        want = truth[col]
        got = _PATTERN_TO_BEHAVIOR.get(pattern, pattern)
        marker = "✓" if got == want else "✗"
        print(f"  {marker} {col}: pattern={pattern} → {got} (truth {want})")
        if got != want:
            mismatches.append(f"  {col}: reconciled {pattern} (→{got}), truth is {want}")

    assert not mismatches, (
        "structural reconciliation contradicts ground truth — a real defect in the "
        "data-grounded stock/flow witness:\n" + "\n".join(mismatches)
    )


@pytest.mark.llm
def test_reconciliation_covers_expected_rollup_measures() -> None:
    """Every rollup measure with a finer event fact reconciles — none is stripped
    (DAT-722). The regression signature is asymmetric: before judge-declined
    relationships were cut at the source, a coincidental conf=0.05
    ``debit → payments.amount`` "FK" stripped ``trial_balance.debit_balance``'s only
    reconciliation convention, so ``credit_balance`` reconciled and ``debit_balance``
    did not (1/2). This guards that exact asymmetry: if the witness fired on ANY
    expected rollup it must have fired on ALL of them.
    """
    _activate_or_skip()
    with workspace_session() as session:
        patterns = read_structural_patterns(session)

    expected: list[str] = load_truth().get("reconciles_structurally") or []
    if not expected:
        pytest.skip("no reconciles_structurally expectations declared")

    reconciled = [c for c in expected if c in patterns]
    if not reconciled:
        pytest.skip("structural witness fired on no expected rollup this run — nothing to cover")

    missing = [c for c in expected if c not in patterns]
    print(f"\n[reconciliation coverage] {len(reconciled)}/{len(expected)} expected rollups reconciled")
    for col in missing:
        print(f"  MISSING (stripped?): {col}")
    assert not missing, (
        "the structural witness reconciled SOME but not all expected rollup measures — "
        "one was stripped from its conventions (the DAT-722 declined-FK signature: "
        "credit reconciles, debit does not):\n  " + "\n  ".join(missing)
    )


@pytest.mark.llm
def test_resolved_stockflow_labels_accuracy() -> None:
    """Reported accuracy of the pooled stock/flow label; soft (LLM-variable).

    A fact with no finer event fact is name-only, and a structurally-contested
    label resolves to the majority name pending teach — both LLM-variable. So a
    divergence is surfaced (xfail), never a hard fail: a miss becomes a teach
    scenario / ticket, never a truth patch (DAT-685 hard rule).
    """
    _activate_or_skip()
    with workspace_session() as session:
        actual = read_temporal_behavior(session)

    truth: dict[str, str] = load_truth().get("stock_flow") or {}
    graded = {col: exp for col, exp in truth.items() if col in actual}
    if not graded:
        pytest.skip("no stock/flow labels produced — temporal_behavior didn't resolve")

    diverged: list[str] = []
    correct = 0
    for col, expected in sorted(graded.items()):
        got = actual[col]
        if got == expected:
            correct += 1
        else:
            diverged.append(f"  {col}: resolved {got}, truth {expected}")

    print(f"\n[resolved stock/flow] {correct}/{len(graded)} match truth on {_STRATEGY}")
    for line in diverged:
        print(line)

    if diverged:
        pytest.xfail(
            "resolved stock/flow labels diverge from truth — name-only variance or "
            "a structurally-contested label pending teach-closure (not a defect):\n"
            + "\n".join(diverged)
        )
