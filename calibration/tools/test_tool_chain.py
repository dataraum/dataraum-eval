"""MCP tool chain — end-to-end sequence through all tools (DAT-217).

Calls handler functions directly against calibration pipeline output.
Verifies each tool returns well-formed responses with expected data.

Prerequisites: pipeline output in output/detection-v1/ (make calibrate).
"""

from __future__ import annotations

from typing import Any

import pytest
from dataraum.mcp.server import _look, _measure, _run_sql

# Same threshold as test_detector_recall.py
DETECTION_THRESHOLD = 0.3

EXPECTED_TABLES = {
    "bank_transactions",
    "chart_of_accounts",
    "fx_rates",
    "invoices",
    "journal_entries",
    "journal_lines",
    "payments",
    "trial_balance",
}


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------


class TestLookDataset:
    def test_returns_tables(self, db_session: Any) -> None:
        result = _look(db_session)
        assert "tables" in result, f"Expected 'tables' key, got: {list(result.keys())}"
        assert isinstance(result["tables"], list)
        assert len(result["tables"]) >= len(EXPECTED_TABLES)

    def test_known_tables_present(self, db_session: Any) -> None:
        result = _look(db_session)
        table_names = {t["name"] for t in result["tables"]}
        for expected in EXPECTED_TABLES:
            assert expected in table_names, f"Missing table: {expected}"

    def test_table_entries_have_columns(self, db_session: Any) -> None:
        result = _look(db_session)
        for table in result["tables"]:
            assert "name" in table
            assert "columns" in table
            assert isinstance(table["columns"], list)
            assert len(table["columns"]) > 0


class TestLookTable:
    def test_invoices_detail(self, db_session: Any) -> None:
        result = _look(db_session, target="invoices")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "columns" in result
        col_names = {c["name"] for c in result["columns"]}
        assert "amount" in col_names
        assert "invoice_id" in col_names

    def test_journal_lines_detail(self, db_session: Any) -> None:
        result = _look(db_session, target="journal_lines")
        assert "error" not in result
        col_names = {c["name"] for c in result["columns"]}
        assert "debit" in col_names
        assert "credit" in col_names


class TestLookColumn:
    def test_column_profile(self, db_session: Any) -> None:
        result = _look(db_session, target="invoices.amount")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "name" in result
        assert result["name"] == "amount"


class TestLookSample:
    def test_sample_rows(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _look(db_session, target="invoices", sample=5, cursor=duckdb_cursor)
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "rows" in result
        assert len(result["rows"]) == 5
        assert "columns" in result


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


class TestMeasure:
    def test_returns_complete_status(self, db_session: Any) -> None:
        result = _measure(db_session)
        assert result["status"] == "complete", f"Expected complete, got: {result.get('status')}"

    def test_has_points(self, db_session: Any) -> None:
        result = _measure(db_session)
        assert "points" in result
        assert isinstance(result["points"], list)
        assert len(result["points"]) > 0

    def test_points_have_required_keys(self, db_session: Any) -> None:
        result = _measure(db_session)
        for point in result["points"][:5]:
            assert "target" in point
            assert "dimension" in point
            assert "score" in point
            assert isinstance(point["score"], (int, float))

    def test_has_layer_scores(self, db_session: Any) -> None:
        result = _measure(db_session)
        assert "scores" in result
        assert isinstance(result["scores"], dict)
        assert len(result["scores"]) > 0

    def test_has_readiness(self, db_session: Any) -> None:
        result = _measure(db_session)
        assert "readiness" in result
        for key, value in result["readiness"].items():
            assert value in ("ready", "investigate", "blocked"), (
                f"Invalid readiness '{value}' for {key}"
            )


class TestMeasureFilter:
    def test_table_filter(self, db_session: Any) -> None:
        result = _measure(db_session, target="invoices")
        assert "error" not in result
        for point in result["points"]:
            target = point["target"]
            assert "invoices" in target, f"Point target '{target}' doesn't match filter"

    def test_column_filter(self, db_session: Any) -> None:
        result = _measure(db_session, target="invoices.amount")
        assert "error" not in result
        for point in result["points"]:
            assert point["target"] == "column:invoices.amount"


class TestMeasureConsistency:
    """Verify measure tool returns scores consistent with calibration harness.

    The calibration harness calls measure_entropy() directly and maps dimension
    paths to detector_ids via the registry. The measure tool returns raw dimension
    paths. This test verifies the underlying data matches.
    """

    def test_scores_match_calibration(
        self,
        db_session: Any,
        pipeline_scores: dict[tuple[str, str, str], float],
    ) -> None:
        """Measure tool's points should cover all high-scoring calibration entries."""
        result = _measure(db_session)
        assert "points" in result

        # Build a set of (table, column) pairs with scores > threshold from measure
        measure_targets: set[tuple[str, str]] = set()
        for point in result["points"]:
            target = point["target"]
            if target.startswith("column:") and point["score"] > DETECTION_THRESHOLD:
                ref = target.removeprefix("column:")
                parts = ref.split(".", 1)
                if len(parts) == 2:
                    measure_targets.add((parts[0], parts[1]))

        # Every (table, column) that scores > threshold in calibration should also
        # appear with a high score in at least one measure point
        missing = []
        for (table, column, detector_id), score in pipeline_scores.items():
            if score <= DETECTION_THRESHOLD:
                continue
            if (table, column) not in measure_targets:
                missing.append(f"{detector_id}:{table}.{column} (score={score:.3f})")

        assert not missing, (
            f"Measure tool missing {len(missing)} high-scoring entries:\n" + "\n".join(missing)
        )

    def test_high_scoring_points_exist(self, db_session: Any) -> None:
        """Measure should surface at least some high-scoring entropy points."""
        result = _measure(db_session)
        high_scores = [p for p in result["points"] if p["score"] > DETECTION_THRESHOLD]
        assert len(high_scores) >= 5, (
            f"Expected ≥5 high-scoring points, got {len(high_scores)}"
        )


# ---------------------------------------------------------------------------
# run_sql
# ---------------------------------------------------------------------------


class TestRunSql:
    def test_basic_count(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _run_sql(db_session, duckdb_cursor, sql="SELECT COUNT(*) AS cnt FROM typed_invoices")
        assert "error" not in result, f"SQL error: {result.get('error')}"
        assert "rows" in result
        assert len(result["rows"]) == 1
        assert result["rows"][0]["cnt"] > 0

    def test_columns_metadata(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _run_sql(db_session, duckdb_cursor, sql="SELECT invoice_id, amount FROM typed_invoices LIMIT 3")
        assert "error" not in result
        assert "columns" in result
        assert "invoice_id" in result["columns"]
        assert "amount" in result["columns"]

    def test_revenue_order_of_magnitude(
        self, db_session: Any, duckdb_cursor: Any, ground_truth: dict[str, Any]
    ) -> None:
        """SQL revenue query returns a result in the right ballpark.

        Injections (outlier_rate, null_ratio) shift amounts, so we only check
        order of magnitude. Financial accuracy is tested by the /deliver skill.
        """
        expected = ground_truth["annual"]["total_revenue"]
        result = _run_sql(
            db_session,
            duckdb_cursor,
            sql=(
                "SELECT SUM(jl.credit) AS total_revenue "
                "FROM typed_journal_lines jl "
                "JOIN typed_chart_of_accounts coa ON jl.account_id = coa.account_id "
                "WHERE coa.account_type = 'revenue' AND jl.credit > 0"
            ),
        )
        assert "error" not in result, f"SQL error: {result.get('error')}"
        actual = result["rows"][0]["total_revenue"]
        assert actual > 0, "Revenue should be positive"
        # Within 50% — injections can shift significantly but not by orders of magnitude
        assert actual > expected * 0.5, f"Revenue too low: {actual:.0f} vs expected {expected:.0f}"
        assert actual < expected * 2.0, f"Revenue too high: {actual:.0f} vs expected {expected:.0f}"

    def test_row_limit(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _run_sql(
            db_session, duckdb_cursor, sql="SELECT * FROM typed_invoices", limit=5
        )
        assert "error" not in result
        assert len(result["rows"]) == 5
        assert result.get("truncated") is True


# ---------------------------------------------------------------------------
# query (LLM-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.llm
class TestQuery:
    def test_revenue_query(
        self, db_session: Any, duckdb_cursor: Any, ground_truth: dict[str, Any]
    ) -> None:
        from dataraum.mcp.server import _query

        result = _query(db_session, duckdb_cursor, "What is the total revenue for fiscal year 2025?")
        assert "error" not in result, f"Query error: {result.get('error')}"
        assert "answer" in result
        assert "confidence" in result
