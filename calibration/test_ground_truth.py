"""Ground truth metrics — do computed values match known answers?

Uses ground_truth.yaml from testdata to verify financial invariants. The
SQL-backed revenue check is skipped in the current slice: it drove the retired
MCP ``_run_sql`` tool (moved to ``reference/mcp/`` in DAT-369), and the cockpit
query surface that replaces it is not exercised by this harness yet.
"""

from __future__ import annotations

from typing import Any

import pytest


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


@pytest.mark.skip(
    reason=(
        "SQL revenue check drove the retired MCP _run_sql tool (DAT-369 moved the "
        "MCP surface to reference/mcp/). Re-enable against the cockpit query path "
        "when this harness exercises it."
    )
)
def test_revenue_matches_ground_truth(ground_truth: dict[str, Any]) -> None:
    """Total revenue from SQL should match ground truth within tolerance."""
