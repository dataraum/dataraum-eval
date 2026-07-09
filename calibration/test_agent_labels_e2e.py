"""Agent-label accuracy vs metadata_truth.yaml (DAT-680 P1, DAT-685).

Grades the pipeline's LLM/detector labels against ground truth. First surface:
``column_concepts.temporal_behavior`` (stock/flow, catalogue grain) — the label
the additivity oracle's ``label_dependent`` cells rest on. (``table_entities``
roles + ``semantic_annotations.semantic_role`` are the next increment.)

Grammar (DAT-685): accuracy reported as a proportion; a column that ground truth
marks correct but the detector now mislabels fails **hard** (a regression, or a
not-yet-filed miss → make it a ticket); a **filed, known** detector gap is
``xfail`` — surfaced, not a build break, and never a truth patch (misses become
teach scenarios / tickets — the no-deterministic-override rule). Tier-3 (docker +
Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import load_truth, read_temporal_behavior
from calibration.tools._runs import workspace_session

_STRATEGY = "clean"

# Known detector gaps on the finance corpus — a real miss, FILED, never patched:
# trial_balance's per-period movements read as `point_in_time` because the word
# "balance" biases the stock/flow detector, though the generator defines them as
# flows (finance/models.py `BalanceSheet` docstring). Listed so the oracle
# surfaces them as xfail while a NEW mislabel still fails loud. See the DAT-685
# stock/flow finding.
_KNOWN_STOCKFLOW_MISSES = {
    "trial_balance.debit_balance",
    "trial_balance.credit_balance",
}


@pytest.mark.llm
def test_stock_flow_labels_vs_truth() -> None:
    """Every truth-correct measure column keeps its correct stock/flow label."""
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {_STRATEGY!r}; run "
            f"`python -m calibration.run -s {_STRATEGY}` first"
        )
    runner_mod.activate_workspace(_STRATEGY)

    with workspace_session() as session:
        actual = read_temporal_behavior(session)

    truth: dict[str, str] = load_truth().get("stock_flow") or {}
    graded = {col: exp for col, exp in truth.items() if col in actual}
    if not graded:
        pytest.skip(
            "no stock/flow labels produced — temporal_behavior didn't resolve "
            f"(present concepts: {sorted(actual)})"
        )

    regressions: list[str] = []  # a truth-correct column the detector now mislabels
    known: list[str] = []  # a filed, known miss
    correct = 0
    for col, expected in sorted(graded.items()):
        got = actual[col]
        if got == expected:
            correct += 1
            continue
        line = f"  {col}: expected {expected}, got {got}"
        (known if col in _KNOWN_STOCKFLOW_MISSES else regressions).append(line)

    print(
        f"\n[stock/flow labels] {correct}/{len(graded)} correct on {_STRATEGY} "
        f"(regressions={len(regressions)} known-misses={len(known)})"
    )
    for line in (*regressions, *known):
        print(line)

    # HARD: a truth-correct column the detector mislabels is a regression (or a
    # miss not yet filed) — fail loud so it becomes a teach scenario / ticket.
    assert not regressions, (
        "stock/flow label regressions — file as teach scenarios / tickets, never "
        "patch the truth:\n" + "\n".join(regressions)
    )
    # SOFT: filed, known detector gaps — surfaced, not a build break.
    if known:
        pytest.xfail(
            "known stock/flow detector gaps (filed, not patched):\n" + "\n".join(known)
        )
