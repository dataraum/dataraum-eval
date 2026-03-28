"""Ground truth metrics — do computed values match known answers?

Uses ground_truth.yaml from testdata to verify the pipeline + MCP tools
produce correct financial metrics. Revenue query uses _run_sql directly.
"""

from __future__ import annotations

from typing import Any

from dataraum.mcp.server import _run_sql


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


def test_revenue_matches_ground_truth(
    ground_truth: dict[str, Any],
    typed_tables: dict[str, str],
    db_session: Any,
    duckdb_cursor: Any,
) -> None:
    """Total revenue from SQL should match ground truth within tolerance.

    Injections (outlier_rate, null_ratio) shift amounts, so we allow 50%
    deviation. This verifies the query path works and returns the right
    order of magnitude — not exact financial accuracy.
    """
    jl = typed_tables["journal_lines"]
    coa = typed_tables["chart_of_accounts"]
    expected = ground_truth["annual"]["total_revenue"]

    result = _run_sql(
        db_session,
        duckdb_cursor,
        sql=(
            f"SELECT SUM(jl.credit) AS total_revenue "
            f"FROM {jl} jl "
            f"JOIN {coa} coa ON jl.account_id = coa.account_id "
            f"WHERE coa.account_type = 'revenue' AND jl.credit > 0"
        ),
    )
    assert "error" not in result, f"SQL error: {result.get('error')}"
    actual = result["rows"][0]["total_revenue"]
    assert actual > expected * 0.5, f"Revenue too low: {actual:.0f} vs expected {expected:.0f}"
    assert actual < expected * 2.0, f"Revenue too high: {actual:.0f} vs expected {expected:.0f}"
