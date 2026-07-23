"""Tier-1: the DAT-856 three-state directed-cycle classifier (pure, milliseconds).

The vocabulary the sweep-#3 gate depends on: DETECTED_BUT_UNDIRECTED is its own
named failure state — a direction gap, never conflated with MISSED — including the
engine's Cut B rendering (an undirected detection surfaces as canonical_type = the
family). WRONG_DIRECTION (a directed row contradicting the declared truth) is a
third distinct state.
"""

from __future__ import annotations

from typing import Any

from calibration.test_cycles_e2e import classify_directed_cycle

_AP = {
    "canonical_type": "accounts_payable",
    "key_tables": ["invoices", "payments"],
    "required": True,
    "family": "settlement",
    "direction": "outgoing",
}


def _row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "canonical_type": "accounts_payable",
        "cycle_name": "AP settlement",
        "is_known_type": True,
        "confidence": 0.9,
        "tables": {"invoices", "payments"},
        "family": "settlement",
        "direction": "outgoing",
        "status_column": None,
        "completion_value": None,
        "completion_rate": None,
    }
    base.update(kw)
    return base


def test_correct_when_type_tables_and_direction_match() -> None:
    state, _ = classify_directed_cycle(_AP, [_row()])
    assert state == "CORRECT"


def test_undirected_on_exact_type_with_undetermined_direction() -> None:
    state, _ = classify_directed_cycle(_AP, [_row(direction="undetermined")])
    assert state == "DETECTED_BUT_UNDIRECTED"


def test_undirected_via_cut_b_family_rendering() -> None:
    # Cut B: canonical_type = the family when undirected — no accounts_payable row.
    state, _ = classify_directed_cycle(
        _AP, [_row(canonical_type="settlement", direction="undetermined")]
    )
    assert state == "DETECTED_BUT_UNDIRECTED"


def test_wrong_direction_is_its_own_state() -> None:
    state, detail = classify_directed_cycle(_AP, [_row(direction="incoming")])
    assert state == "WRONG_DIRECTION" and "incoming" in detail


def test_key_tables_short_wins_over_direction() -> None:
    state, detail = classify_directed_cycle(_AP, [_row(tables={"invoices"})])
    assert state == "KEY_TABLES_SHORT" and "payments" in detail


def test_missed_when_neither_type_nor_family_detected() -> None:
    state, _ = classify_directed_cycle(
        _AP, [_row(canonical_type="bank_reconciliation", family=None, direction=None)]
    )
    assert state == "MISSED"
