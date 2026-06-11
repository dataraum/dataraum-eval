"""Ground truth metrics — do computed values match known answers?

Uses ground_truth.yaml from testdata to verify financial invariants. The
metric-vs-ground-truth comparison itself lives in ``calibration/outcomes.py``
(the golden-SQL labeler behind the scoreboard) — an empty skipped stub that
once drove the retired MCP ``_run_sql`` tool was deleted when the labeler
superseded it (C1 cleanup).
"""

from __future__ import annotations

from typing import Any


def test_ground_truth_loaded(ground_truth: dict[str, Any]) -> None:
    """Verify ground_truth.yaml has expected structure."""
    assert "annual" in ground_truth
    assert "invariants" in ground_truth
    assert "monthly" in ground_truth

    annual = ground_truth["annual"]
    assert "total_revenue" in annual
    assert "total_expenses" in annual
    assert "free_cash_flow" in annual


def test_invariants_hold(ground_truth: dict[str, Any]) -> None:
    """Pre-injection data invariants should be documented."""
    inv = ground_truth["invariants"]
    assert inv["journal_balanced"] is True
    assert inv["trial_balance_balanced"] is True
    assert inv["invoice_payment_matched"] is True
