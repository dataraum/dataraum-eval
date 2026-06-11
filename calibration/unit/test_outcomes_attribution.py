"""Tier-1: prevention attribution as a pure function (B3).

The causal/coincidental decision must be a deterministic set intersection over
(warned lineage columns × banding detectors × injected detectors) — no scores,
no thresholds, no rollup re-derivation here. These tests pin the boundary
cases; the live banding/injected inputs are exercised by the batch runner.
"""

from __future__ import annotations

from calibration.outcomes import _attribute_prevention


def test_causal_when_injected_detector_banded_injected_column() -> None:
    """The clean causal case: warning on the corrupted column, for its reason."""
    attribution, cols = _attribute_prevention(
        warned=["journal_lines.credit"],
        banding={"journal_lines.credit": {"null_ratio", "benford"}},
        injected={"journal_lines.credit": {"null_ratio"}},
    )
    assert attribution == "causal"
    assert cols == ["journal_lines.credit"]


def test_coincidental_when_banding_detector_unrelated_to_injection() -> None:
    """Warned on the injected column but by a detector no injection targets."""
    attribution, cols = _attribute_prevention(
        warned=["invoices.amount"],
        banding={"invoices.amount": {"unit_entropy"}},
        injected={"invoices.amount": {"cross_table_consistency"}},
    )
    assert attribution == "coincidental"
    assert cols == []


def test_related_when_injected_failure_mode_anchors_to_connected_column() -> None:
    """The validation fan-out pattern: TB↔GL tampering (injected on trial_balance)
    bands the GL columns that participate in the broken identity — same detector,
    different column. Related, not coincidental."""
    attribution, cols = _attribute_prevention(
        warned=["journal_lines.credit"],
        banding={"journal_lines.credit": {"cross_table_consistency"}},
        injected={"trial_balance.credit_balance": {"cross_table_consistency"}},
    )
    assert attribution == "related"
    assert cols == []


def test_coincidental_when_warned_column_not_injected() -> None:
    """Warned only via an uninjected lineage column (e.g. clean-data hedging)."""
    attribution, cols = _attribute_prevention(
        warned=["journal_entries.status"],
        banding={"journal_entries.status": {"business_meaning"}},
        injected={"journal_lines.cost_center": {"null_ratio"}},
    )
    assert attribution == "coincidental"
    assert cols == []


def test_one_causal_column_suffices_among_coincidental_ones() -> None:
    """A single causal warning makes the metric's prevention causal."""
    attribution, cols = _attribute_prevention(
        warned=["journal_entries.status", "journal_lines.credit"],
        banding={
            "journal_entries.status": {"business_meaning"},
            "journal_lines.credit": {"null_ratio"},
        },
        injected={"journal_lines.credit": {"null_ratio"}},
    )
    assert attribution == "causal"
    assert cols == ["journal_lines.credit"]


def test_no_warned_columns_is_coincidental_vacuously() -> None:
    """Defensive: attribution is only called for prevented metrics, but an empty
    warned list must not crash and must not claim causality."""
    attribution, cols = _attribute_prevention(warned=[], banding={}, injected={})
    assert attribution == "coincidental"
    assert cols == []
