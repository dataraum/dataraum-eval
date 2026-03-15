"""Ground truth metrics — do computed values match known answers?

Uses ground_truth.yaml from testdata to verify the pipeline + query system
produces correct financial metrics. Requires the MCP query tool or direct
SQL access to pipeline output.

These tests are placeholders until the MCP query integration is wired up.
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


@pytest.mark.skip(reason="Requires MCP query integration — DAT-133 Phase 2")
def test_revenue_matches_ground_truth(ground_truth: dict[str, Any]) -> None:
    """Total revenue from pipeline query should match ground truth within tolerance."""
    # TODO: Use MCP query tool to compute actual revenue
    # expected = ground_truth["annual"]["total_revenue"]
    # actual = mcp_query("SELECT SUM(amount) FROM invoices WHERE status != 'cancelled'")
    # tolerance = 0.01  # 1%
    # assert abs(actual - expected) / expected < tolerance
    pass
