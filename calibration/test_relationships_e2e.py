"""FK-topology recall/precision vs the defined relationship catalog (DAT-680 P1, DAT-684).

Grades the judge-confirmed relationship catalog (``detection_method != 'candidate'``)
against the generator's TRUE FK topology (``metadata_truth.relationships``, taken from
the testdata models' FK docstrings — not from what the LLM accepted, which would be
circular). Two tiers:

* **recall (HARD)** — every true FK is judge-confirmed. Surrogate-aware: a FK
  materialized as a DAT-277 surrogate composite (``_sk__…col…``) counts as found (the
  true column name is a component of the surrogate column). A missing true FK is a
  real recall gap.
* **precision (SOFT)** — no spurious FKs. The judge is nondeterministic on
  value-overlap pairs (period↔period, amount↔amount): a pair it declines one run it
  may confirm the next when its confidence lands above the source-side threshold
  (DAT-722). So a spurious FK is surfaced (xfail) and becomes a ticket/teach scenario,
  never a hard build-break — no override of the LLM's judgment (DAT-685 rule).

Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import (
    expected_relationships,
    fk_edge_satisfies,
    read_defined_relationships,
    read_fk_miss_diagnostic,
)
from calibration.tools._runs import workspace_session

_Edge = tuple[str, str, str, str]  # (from_table, from_col, to_table, to_col)


@pytest.fixture(autouse=True)
def _scoped_run(strategy_name: str) -> None:
    """Grade ONLY the strategy under test against its own truth (DAT-797).

    The module used to hardcode ``clean`` — activating a foreign workspace
    mid-pass poisoned every later read in the same pytest process, and the
    strategy under test was never graded here at all.
    """
    sidecar = runner_mod.sidecar_path(strategy_name)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {strategy_name!r}; run "
            f"`python -m calibration.run -s {strategy_name}` first"
        )
    runner_mod.activate_workspace(strategy_name)


def _satisfies(true_fk: _Edge, defined: set[_Edge]) -> bool:
    """A true FK is present iff some defined edge satisfies it — delegated to the
    shared ``fk_edge_satisfies`` (same tables in the same orientation,
    surrogate-aware column containment) so grading and the miss diagnostic can
    never drift apart."""
    return any(fk_edge_satisfies(d, true_fk) for d in defined)


@pytest.mark.llm
def test_relationship_recall(metadata_truth: dict[str, Any]) -> None:
    """Every true FK (generator topology) is judge-confirmed (surrogate-aware)."""
    with workspace_session() as session:
        defined = read_defined_relationships(session)

        true_fks = expected_relationships(metadata_truth)
        if not true_fks:
            pytest.skip("no relationships ground truth declared")

        missing = [
            t
            for t, reliable in sorted(true_fks.items())
            if not (
                _satisfies(t, defined)
                # direction_reliable=False: the merge destroyed the parent
                # grain — either orientation satisfies (ruling 2026-07-16).
                or (not reliable and _satisfies((t[2], t[3], t[0], t[1]), defined))
            )
        ]
        print(f"\n[relationship recall] {len(true_fks) - len(missing)}/{len(true_fks)} true FKs confirmed")
        for t in missing:
            # Self-documenting miss (learned 2026-07-15, DAT-763 follow-up): print
            # WHY before the workspace is reset. Three distinct bug classes — a
            # flipped confirm is an orientation issue (the judge ACCEPTED the
            # pair), a decline-with-reasoning is a judge/prompt issue, and no
            # candidate at all is a Layer-A gap.
            diag = read_fk_miss_diagnostic(session, *t)
            if diag is None:
                verdict = "never a candidate (Layer-A gap)"
            elif diag["kind"] == "confirmed_flipped":
                verdict = (
                    f"CONFIRMED IN FLIPPED ORIENTATION (conf {diag['confidence']}) "
                    "— truth is direction-exact"
                )
            else:
                verdict = f"judge DECLINED at confidence {diag['confidence']}: {diag['evidence']!r}"
            print(f"  MISSING: {t[0]}.{t[1]} -> {t[2]}.{t[3]} — {verdict}")
    assert not missing, (
        "true FKs (generator topology) absent from the judge-confirmed catalog — a "
        "real recall gap:\n" + "\n".join(f"  {t[0]}.{t[1]} -> {t[2]}.{t[3]}" for t in missing)
    )


@pytest.mark.llm
def test_relationship_precision(metadata_truth: dict[str, Any]) -> None:
    """No spurious FKs; soft (the judge is LLM-variable on value-overlap pairs)."""
    with workspace_session() as session:
        defined = read_defined_relationships(session)

    true_fks = expected_relationships(metadata_truth)
    if not defined:
        pytest.skip("no defined relationships produced")

    spurious = [
        d
        for d in sorted(defined)
        if not any(
            _satisfies(t, {d}) or (not reliable and _satisfies((t[2], t[3], t[0], t[1]), {d}))
            for t, reliable in true_fks.items()
        )
    ]
    print(f"\n[relationship precision] {len(defined) - len(spurious)}/{len(defined)} defined edges are true FKs")
    for d in spurious:
        print(f"  SPURIOUS: {d[0]}.{d[1]} -> {d[2]}.{d[3]}")

    if spurious:
        pytest.xfail(
            "spurious defined FK(s) — the judge over-confirmed a value-overlap pair "
            "(LLM-nondeterministic; a ticket/teach scenario, not a truth patch):\n"
            + "\n".join(f"  {d[0]}.{d[1]} -> {d[2]}.{d[3]}" for d in spurious)
        )
