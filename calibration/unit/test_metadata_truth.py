"""Tier-1: metadata_truth.yaml is well-formed and internally consistent.

The additivity oracle (``test_metric_additivity_e2e``) is Tier-3 (docker + LLM),
so this ms-level gate guards the ground-truth fixture itself: every verdict names
a legal reason, a reason is present exactly when its axis is non-additive, and the
flatten the oracle consumes produces the expected ``(kind, key)`` keys. A typo in
the fixture would otherwise only surface in a 10-minute run.
"""

from __future__ import annotations

import pytest

from calibration.metadata_truth import expected_additivity, load_truth

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
