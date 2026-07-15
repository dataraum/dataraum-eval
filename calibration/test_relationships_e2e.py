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

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import (
    expected_relationships,
    load_truth,
    read_candidate_relationship,
    read_defined_relationships,
)
from calibration.tools._runs import workspace_session

_STRATEGY = "clean"

_Edge = tuple[str, str, str, str]  # (from_table, from_col, to_table, to_col)


def _activate_or_skip() -> None:
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {_STRATEGY!r}; run "
            f"`python -m calibration.run -s {_STRATEGY}` first"
        )
    runner_mod.activate_workspace(_STRATEGY)


def _satisfies(true_fk: _Edge, defined: set[_Edge]) -> bool:
    """A true FK is present iff a defined edge joins the same tables and carries the
    true columns — exactly, or as a surrogate whose column name contains them (a
    DAT-277 ``_sk__date__payment_id`` embeds ``payment_id``)."""
    tft, tfc, ttt, ttc = true_fk
    return any(
        dft == tft and dtt == ttt and tfc in dfc and ttc in dtc
        for (dft, dfc, dtt, dtc) in defined
    )


@pytest.mark.llm
def test_relationship_recall() -> None:
    """Every true FK (generator topology) is judge-confirmed (surrogate-aware)."""
    _activate_or_skip()
    with workspace_session() as session:
        defined = read_defined_relationships(session)

        true_fks = expected_relationships(load_truth())
        if not true_fks:
            pytest.skip("no relationships ground truth declared")

        missing = [t for t in sorted(true_fks) if not _satisfies(t, defined)]
        print(f"\n[relationship recall] {len(true_fks) - len(missing)}/{len(true_fks)} true FKs confirmed")
        for t in missing:
            # Self-documenting miss (learned 2026-07-15, DAT-763 follow-up): a
            # declined pair persists as 'candidate' with the judge's evidence, so
            # print WHY before the workspace is reset — decline-with-reasoning is
            # a judge/prompt issue, no candidate at all is a Layer-A gap.
            cand = read_candidate_relationship(session, *t)
            verdict = (
                f"judge DECLINED at confidence {cand['confidence']}: {cand['evidence']!r}"
                if cand
                else "never a candidate (Layer-A gap)"
            )
            print(f"  MISSING: {t[0]}.{t[1]} -> {t[2]}.{t[3]} — {verdict}")
    assert not missing, (
        "true FKs (generator topology) absent from the judge-confirmed catalog — a "
        "real recall gap:\n" + "\n".join(f"  {t[0]}.{t[1]} -> {t[2]}.{t[3]}" for t in missing)
    )


@pytest.mark.llm
def test_relationship_precision() -> None:
    """No spurious FKs; soft (the judge is LLM-variable on value-overlap pairs)."""
    _activate_or_skip()
    with workspace_session() as session:
        defined = read_defined_relationships(session)

    true_fks = expected_relationships(load_truth())
    if not defined:
        pytest.skip("no defined relationships produced")

    spurious = [d for d in sorted(defined) if not any(_satisfies(t, {d}) for t in true_fks)]
    print(f"\n[relationship precision] {len(defined) - len(spurious)}/{len(defined)} defined edges are true FKs")
    for d in spurious:
        print(f"  SPURIOUS: {d[0]}.{d[1]} -> {d[2]}.{d[3]}")

    if spurious:
        pytest.xfail(
            "spurious defined FK(s) — the judge over-confirmed a value-overlap pair "
            "(LLM-nondeterministic; a ticket/teach scenario, not a truth patch):\n"
            + "\n".join(f"  {d[0]}.{d[1]} -> {d[2]}.{d[3]}" for d in spurious)
        )
