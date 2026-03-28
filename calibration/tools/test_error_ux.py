"""Error UX — tool error messages are clear and actionable (DAT-218).

Each test verifies that invalid input produces a helpful error message,
not a traceback or cryptic internal error.
"""

from __future__ import annotations

from typing import Any

from dataraum.mcp.server import _begin_session, _look, _measure, _run_sql


class TestLookErrors:
    def test_nonexistent_table(self, db_session: Any) -> None:
        result = _look(db_session, target="nonexistent_table_xyz")
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert "Available" in result["error"]

    def test_nonexistent_column(self, db_session: Any) -> None:
        result = _look(db_session, target="invoices.nonexistent_column_xyz")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_sample_without_table(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _look(db_session, sample=5, cursor=duckdb_cursor)
        assert "error" in result
        assert "target" in result["error"].lower() or "table" in result["error"].lower()


class TestMeasureErrors:
    def test_nonexistent_table(self, db_session: Any) -> None:
        result = _measure(db_session, target="nonexistent_table_xyz")
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert "Available" in result["error"]


class TestRunSqlErrors:
    def test_invalid_sql(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _run_sql(db_session, duckdb_cursor, sql="SELECT FROM WHERE INVALID")
        assert "error" in result

    def test_no_input(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _run_sql(db_session, duckdb_cursor)
        assert "error" in result
        assert "steps" in result["error"].lower() or "sql" in result["error"].lower()

    def test_both_inputs(self, db_session: Any, duckdb_cursor: Any) -> None:
        result = _run_sql(
            db_session,
            duckdb_cursor,
            steps=[{"step_id": "test", "sql": "SELECT 1"}],
            sql="SELECT 1",
        )
        assert "error" in result
        assert "not both" in result["error"].lower()


class TestBeginSessionErrors:
    def test_unknown_contract(self, db_session: Any) -> None:
        result = _begin_session(db_session, intent="test", contract="nonexistent_contract_xyz")
        assert "error" in result
