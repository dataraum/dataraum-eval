"""Error UX — tool error responses are clear and actionable (DAT-218).

Each test verifies that invalid input produces a helpful error message,
not a traceback or cryptic internal error. Runs against the live HTTP
MCP control plane.
"""

from __future__ import annotations

from typing import Any

from calibration.mcp_client import call_tool

from .conftest import end_active_session


class TestLookErrors:
    async def test_nonexistent_table(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {"target": "nonexistent_table_xyz"})
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert "Available" in result["error"]

    async def test_nonexistent_column(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session, "look", {"target": "invoices.nonexistent_column_xyz"}
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_sample_without_table(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {"sample": 5})
        assert "error" in result
        assert "target" in result["error"].lower() or "table" in result["error"].lower()


class TestMeasureErrors:
    async def test_nonexistent_table(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session, "measure", {"target": "nonexistent_table_xyz"}
        )
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert "Available" in result["error"]


class TestRunSqlErrors:
    async def test_invalid_sql_repaired_or_errored(self, detection_v1_session: Any) -> None:
        """Invalid SQL is either repaired by LLM or returns an error."""
        result = await call_tool(
            detection_v1_session, "run_sql", {"sql": "SELECT FROM WHERE INVALID"}
        )
        if "error" in result:
            assert isinstance(result["error"], str)
        else:
            assert "rows" in result or "columns" in result

    async def test_no_input(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "run_sql", {})
        assert "error" in result
        assert "steps" in result["error"].lower() or "sql" in result["error"].lower()

    async def test_both_inputs(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session,
            "run_sql",
            {
                "steps": [{"step_id": "test", "sql": "SELECT 1"}],
                "sql": "SELECT 1",
            },
        )
        assert "error" in result
        assert "not both" in result["error"].lower()


class TestBeginSessionErrors:
    async def test_unknown_contract(self, mcp_client: Any) -> None:
        await end_active_session(mcp_client)
        result = await call_tool(
            mcp_client,
            "begin_session",
            {
                "source": "detection_v1",
                "intent": "test",
                "contract": "nonexistent_contract_xyz",
            },
        )
        assert "error" in result
