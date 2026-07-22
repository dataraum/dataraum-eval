"""Bus-matrix e2e grading (DAT-762 Phase E, evaluation component 3).

Grades the engine's PERSISTED ``current_bus_matrix`` cells against the
generator's ``bus_matrix`` / ``folded_dimensions`` / ``degenerate_ids`` truth
on a completed run. Structure is graded, never words (DAT-769 ruling): cells
match on (fact, attachment, key column), and cross-fact folded identity is
graded as the folded facts SHARING one concept label under 'judge' provenance
— the label's wording is reported, not asserted.

Assertion tiers:
- referenced recall — HARD: every truth ``referenced`` cell has an engine
  referenced cell carrying the truth key in its roles (structural leg,
  deterministic).
- folded recall + conformity — HARD: every fold lands as a folded cell on
  every ``folded_into`` fact (roles = fold key); with ≥2 folded facts the
  cells share one concept label with confirmation_source='judge' (the conform
  judge's cross-fact claim — the capability this ticket adds).
- degenerate abstain — HARD: a ``degenerate_ids`` column never appears in any
  folded/referenced cell (the abstention the DAT-757 gate proved necessary).
  The engine emits no ``degenerate`` cell of its own — ``attachment`` is a
  CHECK-constrained ``folded``/``referenced`` vocabulary, and the near-key
  half of the concept died with the shape router (DAT-762). Truth keeps
  ``degenerate_ids`` as the abstention oracle above; it is a recorded
  acceptance boundary, not a cell to recall.
- ``key_only`` truth cells — REPORTED only: they sit on the Layer-A blind-spot
  FK classes (DAT-762 comments 16642/16643), the lane's recorded acceptance
  boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration import runner as runner_mod
from calibration.metadata_truth import (
    expected_bus_matrix,
    expected_degenerate_ids,
    expected_folded_dimensions,
    read_view_exists,
)
from calibration.tools._runs import short, workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="begin_session")


@pytest.fixture(scope="module")
def engine_cells(strategy_name: str) -> list[dict[str, Any]]:
    """All persisted bus-matrix cells of the strategy's promoted run, by fact name."""
    from sqlalchemy import text

    if not runner_mod.sidecar_path(strategy_name).exists():
        pytest.skip(
            f"no completed run for {strategy_name!r}; run "
            f"`python -m calibration.run -s {strategy_name}` first"
        )
    runner_mod.activate_workspace(strategy_name)

    from dataraum.storage.read_views import read_schema_name_for

    with workspace_session() as session:
        read_schema = read_schema_name_for(
            str(session.execute(text("SELECT current_schema()")).scalar())
        )
        # Skip ONLY for the one capability case this oracle is allowed to stand
        # down on — the view genuinely not existing. A bare `except Exception`
        # here used to swallow every query error and take all four bus-matrix
        # tests with it, silently, while the run still reported PASS.
        if not read_view_exists(session, "current_bus_matrix"):
            pytest.skip(
                "current_bus_matrix not present — the run predates the DAT-762 "
                "engine build; re-run the pipeline on the lane code"
            )
        rows = session.execute(
            text(
                "SELECT t.table_name AS fact, b.attachment AS attachment, "
                "b.concept_label AS concept_label, b.roles AS roles, "
                "b.attributes AS attributes, "
                "b.confirmation_source AS confirmation_source, "
                "b.conformed_group AS conformed_group, "
                "b.needs_confirmation AS needs_confirmation "
                f'FROM "{read_schema}".current_bus_matrix b '
                "JOIN tables t ON t.table_id = b.fact_table_id"
            )
        ).all()
    return [
        {
            "fact": short(r.fact),
            "attachment": r.attachment,
            "concept_label": r.concept_label,
            "roles": list(r.roles),
            "attributes": list(r.attributes),
            "confirmation_source": r.confirmation_source,
            "conformed_group": r.conformed_group,
            "needs_confirmation": r.needs_confirmation,
        }
        for r in rows
    ]


def test_referenced_recall(
    engine_cells: list[dict[str, Any]], metadata_truth: dict[str, Any]
) -> None:
    """Every truth referenced cell exists structurally (fact + key in roles)."""
    truth = expected_bus_matrix(metadata_truth)
    wanted = [
        (fact, cell["key"], concept)
        for fact, concepts in truth.items()
        for concept, cell in concepts.items()
        if cell["provenance"] == "referenced"
    ]
    if not wanted:
        pytest.skip("no referenced cells in this strategy's truth")
    missing = [
        f"{fact}.{key} (concept {concept})"
        for fact, key, concept in wanted
        if not any(
            c["fact"] == fact and c["attachment"] == "referenced" and key in c["roles"]
            for c in engine_cells
        )
    ]
    assert not missing, "referenced bus-matrix cells missing: " + ", ".join(missing)


def test_folded_recall_and_conformity(
    engine_cells: list[dict[str, Any]], metadata_truth: dict[str, Any]
) -> None:
    """Each fold lands on every folded fact; cross-fact identity is judge-conformed."""
    folds = expected_folded_dimensions(metadata_truth)
    if not folds:
        pytest.skip("no folded_dimensions truth for this strategy (normalized run)")

    problems: list[str] = []
    for fold in folds:
        key, facts = fold["fold_key"], list(fold["folded_into"])
        cells_by_fact: dict[str, dict[str, Any]] = {}
        for fact in facts:
            matches = [
                c
                for c in engine_cells
                if c["fact"] == fact and c["attachment"] == "folded" and key in c["roles"]
            ]
            if not matches:
                problems.append(f"{fact}: no folded cell on key {key!r}")
                continue
            cells_by_fact[fact] = matches[0]
        if len(facts) >= 2 and len(cells_by_fact) == len(facts):
            # The cross-fact claim: ONE conformed_group (the judge's identity
            # assertion — the DAT-800 group key), with the canonicalized label
            # shared across the group. Both graded among the cells
            # (structure), never vs a truth word.
            groups = {c["conformed_group"] for c in cells_by_fact.values()}
            labels = {c["concept_label"] for c in cells_by_fact.values()}
            sources = {c["confirmation_source"] for c in cells_by_fact.values()}
            if len(groups) != 1 or None in groups:
                problems.append(
                    f"fold {key!r}: facts {facts} carry conformed_group={sorted(map(str, groups))}"
                    " — cross-fact identity not conformed"
                )
            elif len(labels) != 1:
                problems.append(
                    f"fold {key!r}: one conformed_group but drifting labels {sorted(labels)} "
                    "— the conform pass's canonicalization is broken"
                )
            elif sources != {"judge"}:
                problems.append(
                    f"fold {key!r}: conformed but confirmation_source={sorted(sources)} "
                    "(expected the conform judge's claim)"
                )
    assert not problems, "; ".join(problems)


def test_degenerate_ids_never_asserted(
    engine_cells: list[dict[str, Any]], metadata_truth: dict[str, Any]
) -> None:
    """A degenerate identifier never rides a folded/referenced cell (abstain)."""
    degenerate = expected_degenerate_ids(metadata_truth)
    if not degenerate:
        pytest.skip("no degenerate_ids truth for this strategy")
    violations = [
        f"{c['fact']}.{col} asserted as {c['attachment']}"
        for qualified in degenerate
        for fact, col in [qualified.split(".", 1)]
        for c in engine_cells
        if c["fact"] == fact
        and c["attachment"] in ("referenced", "folded")
        and (col in c["roles"] or col in c["attributes"])
    ]
    assert not violations, "; ".join(violations)


def test_boundary_report(
    engine_cells: list[dict[str, Any]], metadata_truth: dict[str, Any]
) -> None:
    """REPORT-ONLY: key_only boundary + extra cells."""
    truth = expected_bus_matrix(metadata_truth)

    key_only = [
        f"{fact} x {concept} (key {cell['key']})"
        for fact, concepts in truth.items()
        for concept, cell in concepts.items()
        if cell["provenance"] == "key_only"
    ]
    for entry in key_only:
        print(f"key_only truth cell (Layer-A boundary, ungraded): {entry}")

    truth_folded_keys = {
        (fact, cell["key"])
        for fact, concepts in truth.items()
        for concept, cell in concepts.items()
        if cell["provenance"] == "folded"
    }
    for c in engine_cells:
        if c["attachment"] == "folded" and not any(
            c["fact"] == fact and key in c["roles"] for fact, key in truth_folded_keys
        ):
            print(
                f"extra folded cell (undeclared in truth): {c['fact']} "
                f"roles={c['roles']} label={c['concept_label']!r} "
                f"source={c['confirmation_source']}"
            )
