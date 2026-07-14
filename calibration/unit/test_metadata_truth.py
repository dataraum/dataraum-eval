"""Tier-1: metadata_truth.yaml is well-formed and internally consistent.

The additivity oracle (``test_metric_additivity_e2e``) is Tier-3 (docker + LLM),
so this ms-level gate guards the ground-truth fixture itself: every verdict names
a legal reason, a reason is present exactly when its axis is non-additive, and the
flatten the oracle consumes produces the expected ``(kind, key)`` keys. A typo in
the fixture would otherwise only surface in a 10-minute run.
"""

from __future__ import annotations

import pytest
from testdata.metadata_truth import canonical_metadata_truth, remap_metadata_truth

from calibration.metadata_truth import (
    expected_additivity,
    expected_degenerate_ids,
    expected_folded_dimensions,
    load_truth,
)

# The engine's reason vocabulary (dataraum.graphs.additivity) — the only strings a
# non-additive axis may carry; a reconciling axis carries None.
_REASONS = {
    "stock",
    "average",
    "distinct_count",
    "snapshot_count",
    "min_max",
    "ratio",
    "unknown_aggregate",
    "unknown_temporal",
}
_DETERMINISM = {"function_symmetry", "label_dependent"}


def test_fixture_matches_generator() -> None:
    """The committed fixture is the testdata generator's export — bind them so they
    can never drift (DAT-682: dataraum-testdata is the single source of this truth).

    If this fails, the generator changed: rerun ``scripts/regen_metadata_truth.py``
    (never hand-edit the fixture) or reconcile the generator.
    """
    assert load_truth() == canonical_metadata_truth()


def test_fixture_loads_and_has_additivity() -> None:
    truth = load_truth()
    assert truth.get("vertical") == "finance"
    assert expected_additivity(truth), "metric_additivity flattened to nothing"


def test_flatten_keys_are_kinded() -> None:
    keyed = expected_additivity(load_truth())
    kinds = {kind for (kind, _key) in keyed}
    assert kinds <= {"metric", "measure"}
    # The DAT-718 additions must be present as metric targets.
    for key in ("average_transaction_value", "active_accounts", "transaction_count"):
        assert ("metric", key) in keyed, f"missing metric target {key}"


def test_stock_flow_values_are_legal() -> None:
    """Every stock_flow ground-truth value is a legal temporal_behavior (DAT-685)."""
    stock_flow = load_truth().get("stock_flow") or {}
    assert stock_flow, "stock_flow ground truth is empty"
    for col, behavior in stock_flow.items():
        assert "." in col, f"stock_flow key {col!r} must be 'table.column'"
        assert behavior in {"additive", "point_in_time"}, f"{col}: illegal {behavior!r}"


def test_reconciles_structurally_is_a_stock_flow_subset() -> None:
    """Expected-to-reconcile measures must be declared stock_flow columns (DAT-722)
    — keeps the reconciliation-coverage guard from drifting out of the truth."""
    truth = load_truth()
    stock_flow = truth.get("stock_flow") or {}
    expected = truth.get("reconciles_structurally") or []
    assert expected, "reconciles_structurally is empty"
    for col in expected:
        assert col in stock_flow, f"{col!r} not a declared stock_flow column"


def test_relationships_are_well_formed() -> None:
    """Every relationships ground-truth edge is 'table.column' on both sides (DAT-684)."""
    rels = load_truth().get("relationships") or []
    assert rels, "relationships ground truth is empty"
    for rel in rels:
        assert {"from", "to"} <= set(rel), f"relationship {rel} needs from/to"
        for side in ("from", "to"):
            assert str(rel[side]).count(".") == 1, (
                f"relationship {side}={rel[side]!r} must be 'table.column'"
            )


def test_cycles_are_well_formed() -> None:
    """Every cycles ground-truth entry has a canonical_type + non-empty key_tables (DAT-686)."""
    cycles = load_truth().get("cycles") or []
    assert cycles, "cycles ground truth is empty"
    for c in cycles:
        assert c.get("canonical_type"), f"cycle {c} needs canonical_type"
        assert isinstance(c.get("key_tables"), list) and c["key_tables"], (
            f"cycle {c} needs a non-empty key_tables list"
        )


def test_table_roles_are_disjoint_and_named() -> None:
    """facts/dimensions/ambiguous partition tables with no overlap (DAT-685)."""
    roles = load_truth().get("table_roles") or {}
    facts = set(roles.get("facts") or [])
    dims = set(roles.get("dimensions") or [])
    amb = set(roles.get("ambiguous") or [])
    assert facts and dims, "table_roles needs non-empty facts + dimensions"
    assert facts.isdisjoint(dims) and facts.isdisjoint(amb) and dims.isdisjoint(amb), (
        "a table appears in more than one of facts/dimensions/ambiguous"
    )


def test_semantic_roles_are_well_formed() -> None:
    """measure/timestamp truth is 'table.column', disjoint, non-empty (DAT-685)."""
    sr = load_truth().get("semantic_roles") or {}
    measure = set(sr.get("measure") or [])
    timestamp = set(sr.get("timestamp") or [])
    assert measure and timestamp, "semantic_roles needs non-empty measure + timestamp"
    assert measure.isdisjoint(timestamp), "a column is both measure and timestamp"
    for col in measure | timestamp:
        assert str(col).count(".") == 1, f"semantic_roles key {col!r} must be 'table.column'"


def test_business_concepts_required_is_well_formed() -> None:
    """Every required business_concept binding is 'table.column' → non-empty concept (DAT-685)."""
    required = (load_truth().get("business_concepts") or {}).get("required") or {}
    assert required, "business_concepts.required is empty"
    for col, concept in required.items():
        assert str(col).count(".") == 1, f"business_concept key {col!r} must be 'table.column'"
        assert concept and isinstance(concept, str), f"{col}: concept must be a non-empty string"


# --- folded dimensions (DAT-757) --------------------------------------------
# The committed fixture is `full` → no folds; the folded truth is level-specific, so
# these gates exercise the generator's per-level output directly (ms, no corpus).


def test_folded_dimensions_empty_at_full() -> None:
    """The `full` corpus is normalized — nothing is folded, nothing is degenerate."""
    truth = load_truth()
    assert expected_folded_dimensions(truth) == []
    assert expected_degenerate_ids(truth) == set()


@pytest.mark.parametrize("level", ["flat", "single"])
def test_folded_dimensions_well_formed_at_denormalized_level(level: str) -> None:
    """Every folded-dimension entry names a concept, a fold key, non-empty attributes,
    and at least one fact it is folded into (DAT-757)."""
    folded = expected_folded_dimensions(remap_metadata_truth(canonical_metadata_truth(), level=level))
    assert folded, f"{level}: expected a folded dimension, got none"
    for fold in folded:
        assert fold.get("concept"), f"{level}: folded dim missing concept"
        assert fold.get("fold_key"), f"{level}: folded dim missing fold_key"
        attrs = fold.get("attributes") or []
        assert attrs, f"{level}: folded dim has no attributes"
        into = fold.get("folded_into") or []
        assert isinstance(into, list) and into, f"{level}: folded dim not folded into any fact"


def test_flat_account_dim_is_shared_across_two_facts() -> None:
    """The cross-fact identity case: at `flat`, the account concept is folded into BOTH
    general_ledger and trial_balance → they are ONE dimension (DAT-757 AC)."""
    folded = expected_folded_dimensions(remap_metadata_truth(canonical_metadata_truth(), level="flat"))
    account = next((f for f in folded if f["concept"] == "account"), None)
    assert account is not None, "account folded dimension missing at flat"
    assert set(account["folded_into"]) >= {"general_ledger", "trial_balance"}


@pytest.mark.parametrize("level", ["flat", "single"])
def test_degenerate_ids_well_formed_and_disjoint_from_folds(level: str) -> None:
    """Degenerate IDs are `table.column` operational PKs, and none is also a folded
    attribute or a fold key (an abstain must not be claimed as identity) — DAT-757."""
    truth = remap_metadata_truth(canonical_metadata_truth(), level=level)
    degenerate = expected_degenerate_ids(truth)
    assert degenerate, f"{level}: expected a degenerate operational id"
    fold_cols = {
        a for fold in expected_folded_dimensions(truth) for a in [*fold["attributes"], fold["fold_key"]]
    }
    for col in degenerate:
        assert col.count(".") == 1, f"degenerate id {col!r} must be 'table.column'"
        assert col.split(".", 1)[1] not in fold_cols, f"{col} is both degenerate and a folded column"


@pytest.mark.parametrize("target", sorted(expected_additivity(load_truth())))
def test_each_verdict_is_consistent(target: tuple[str, str]) -> None:
    spec = expected_additivity(load_truth())[target]

    assert spec.get("determinism") in _DETERMINISM, f"{target}: bad determinism"
    for axis, reason_key in (
        ("categorical_additive", "categorical_reason"),
        ("time_additive", "time_reason"),
    ):
        assert isinstance(spec.get(axis), bool), f"{target}: {axis} must be bool"
        reason = spec.get(reason_key)
        if spec[axis]:
            # A reconciling axis carries no reason.
            assert reason is None, f"{target}: {reason_key} set on an additive axis"
        else:
            # A non-additive axis names a legal reason.
            assert reason in _REASONS, f"{target}: {reason_key}={reason!r} not in vocab"
