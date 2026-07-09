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
