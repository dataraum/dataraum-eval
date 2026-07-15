"""Folded-dimension identity e2e (DAT-770): grade the engine's DAT-761 folded
groups against the generator's ``folded_dimensions`` truth.

Runs only on strategies whose truth declares folds (a denormalized scenario —
``clean-flat`` is the first); everywhere else the truth is empty and the module
skips. Two layers:

- truth shape: the derived ``bus_matrix`` must be consistent with
  ``folded_dimensions`` (every folded fact carries a ``folded`` cell on the same
  key) — a generation-side oracle sanity check, no pipeline needed.
- recall: for every fold, on every fact it folded into, the engine's
  ``current_dimension_hierarchies`` member columns must cover the fold key and
  every folded attribute. Detection is the v4 stats stack (``g3`` +
  perm-p/BH/λ — deterministic, no LLM), so this asserts hard: a miss is a
  finding, not noise. ``needs_confirmation`` rows count as detected — presence
  is graded, not confidence (the DAT-762 judge will rule on those).

The persisted bus-matrix cells themselves are graded in DAT-762 Phase E once
the engine persists them; until then ``expected_bus_matrix`` grades shape only.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import (
    expected_bus_matrix,
    expected_folded_dimensions,
)
from calibration.tools._runs import short, workspace_session


@pytest.fixture(scope="module")
def folds(metadata_truth: dict[str, Any]) -> list[dict[str, Any]]:
    entries = expected_folded_dimensions(metadata_truth)
    if not entries:
        pytest.skip("no folded_dimensions truth for this strategy (normalized run)")
    return entries


def test_folded_truth_shape(
    folds: list[dict[str, Any]], metadata_truth: dict[str, Any]
) -> None:
    """The derived bus_matrix agrees with the authored folds (oracle sanity)."""
    matrix = expected_bus_matrix(metadata_truth)
    assert matrix, "folded_dimensions declared but bus_matrix truth is empty"
    for fold in folds:
        concept, key = fold["concept"], fold["fold_key"]
        for fact in fold["folded_into"]:
            cell = matrix.get(fact, {}).get(concept)
            assert cell is not None, f"bus_matrix has no {fact} x {concept} cell"
            assert cell["provenance"] == "folded", (
                f"{fact} x {concept}: expected folded, got {cell['provenance']}"
            )
            assert cell["key"] == key


def test_folded_dimension_recall(
    folds: list[dict[str, Any]], strategy_name: str
) -> None:
    """Every folded attribute is grouped to its fold key by the engine."""
    from sqlalchemy import text

    if not runner_mod.sidecar_path(strategy_name).exists():
        pytest.skip(
            f"no completed run for {strategy_name!r}; run "
            f"`python -m calibration.run -s {strategy_name}` first"
        )
    runner_mod.activate_workspace(strategy_name)

    with workspace_session() as session:
        rows = session.execute(
            text(
                "SELECT t.table_name AS table_name, h.kind AS kind, "
                "h.members AS members, h.needs_confirmation AS needs_confirmation "
                "FROM current_dimension_hierarchies h "
                "JOIN tables t ON t.table_id = h.table_id"
            )
        ).all()

    grouped_cols: dict[str, set[str]] = {}
    for r in rows:
        cols = {str(m["column_name"]) for m in r.members}
        grouped_cols.setdefault(short(r.table_name), set()).update(cols)

    missing: list[str] = []
    for fold in folds:
        expected = {fold["fold_key"], *fold["attributes"]}
        for fact in fold["folded_into"]:
            got = grouped_cols.get(fact, set())
            for col in sorted(expected - got):
                missing.append(f"{fact}.{col} (concept {fold['concept']})")

    assert not missing, (
        "folded-dimension columns never grouped by the engine: " + ", ".join(missing)
    )
