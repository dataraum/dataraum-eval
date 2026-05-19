"""MCP tool chain — end-to-end sequence through all tools (DAT-217).

Drives the dataraum control plane over HTTP MCP. Each test asserts that the
tool returns a well-formed response with the expected data shape.

Prerequisites: pipeline output for `detection-v1` (auto-set up by the
``detection_v1_session`` fixture; first run triggers the pipeline).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from calibration.mcp_client import call_tool

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

# DuckDB table names for the detection-v1 source — raw SQL needs the full
# source-prefixed identifier; the look/measure tools accept short names.
SOURCE = "detection_v1"


def typed(short: str) -> str:
    return f"typed_{SOURCE}__{short}"


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------


class TestLookDataset:
    async def test_returns_tables(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {})
        assert "tables" in result, f"Expected 'tables' key, got: {sorted(result.keys())}"
        assert isinstance(result["tables"], list)
        assert len(result["tables"]) >= len(EXPECTED_TABLES)

    async def test_known_tables_present(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {})
        table_names = {t["name"] for t in result["tables"]}
        for expected in EXPECTED_TABLES:
            found = any(name == expected or name.endswith(f"__{expected}") for name in table_names)
            assert found, f"Missing table: {expected} (available: {table_names})"

    async def test_table_entries_have_columns(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {})
        for table in result["tables"]:
            assert "name" in table
            assert "columns" in table
            assert isinstance(table["columns"], list)
            assert len(table["columns"]) > 0


class TestLookTable:
    async def test_invoices_detail(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {"target": "invoices"})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "columns" in result
        col_names = {c["name"] for c in result["columns"]}
        assert "amount" in col_names
        assert "invoice_id" in col_names

    async def test_journal_lines_detail(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {"target": "journal_lines"})
        assert "error" not in result
        col_names = {c["name"] for c in result["columns"]}
        assert "debit" in col_names
        assert "credit" in col_names


class TestLookColumn:
    async def test_column_profile(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "look", {"target": "invoices.amount"})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "name" in result
        assert result["name"] == "amount"


class TestLookSample:
    @pytest.mark.xfail(
        reason=(
            "Upstream: post-DAT-323 each session gets its own lake.session_<id> "
            "schema, but the fixture's resume_session call can't bind to the "
            "archived session's populated schema — _restore_archived_session "
            "generates a NEW session_id via begin_session() and binds the "
            "manager to that empty schema (server.py:1619-1631). Look(sample=N) "
            "queries the typed table by unqualified name and misses. See "
            "HANDOFF.md in vendor/dataraum-context/."
        ),
        strict=True,
    )
    async def test_sample_rows(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session, "look", {"target": "invoices", "sample": 5}
        )
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "rows" in result
        assert len(result["rows"]) == 5
        assert "columns" in result


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


class TestMeasure:
    async def test_returns_complete_status(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {})
        assert result["status"] == "complete", f"Expected complete, got: {result.get('status')}"

    async def test_has_points(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {})
        assert "points" in result
        assert isinstance(result["points"], list)
        assert len(result["points"]) > 0

    async def test_points_have_required_keys(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {})
        for point in result["points"][:5]:
            assert "target" in point
            assert "dimension" in point
            assert "detector_id" in point
            assert "score" in point
            assert isinstance(point["score"], int | float)

    async def test_has_layer_scores(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {})
        assert "scores" in result
        assert isinstance(result["scores"], dict)
        assert len(result["scores"]) > 0

    async def test_has_readiness(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {})
        assert "readiness" in result
        for key, value in result["readiness"].items():
            assert value in ("ready", "investigate", "blocked"), (
                f"Invalid readiness '{value}' for {key}"
            )


class TestMeasureFilter:
    async def test_table_filter(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {"target": "invoices"})
        assert "error" not in result
        for point in result["points"]:
            assert "invoices" in point["target"], (
                f"Point target '{point['target']}' doesn't match filter"
            )

    async def test_column_filter(self, detection_v1_session: Any) -> None:
        result = await call_tool(detection_v1_session, "measure", {"target": "invoices.amount"})
        assert "error" not in result
        for point in result["points"]:
            assert point["target"].endswith("invoices.amount"), (
                f"Unexpected target: {point['target']}"
            )


class TestMeasureHighScores:
    async def test_high_scoring_points_exist(self, detection_v1_session: Any) -> None:
        """detection-v1 has 14 injections; measure should surface ≥5 high-scoring points."""
        result = await call_tool(detection_v1_session, "measure", {})
        high_scores = [p for p in result["points"] if p["score"] > DETECTION_THRESHOLD]
        assert len(high_scores) >= 5, (
            f"Expected ≥5 high-scoring points, got {len(high_scores)}"
        )


# ---------------------------------------------------------------------------
# run_sql
# ---------------------------------------------------------------------------


class TestRunSql:
    async def test_basic_count(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session,
            "run_sql",
            {"sql": f"SELECT COUNT(*) AS cnt FROM {typed('invoices')}"},
        )
        assert "error" not in result, f"SQL error: {result.get('error')}"
        assert "rows" in result
        assert len(result["rows"]) == 1
        assert result["rows"][0]["cnt"] > 0

    @pytest.mark.xfail(
        reason=(
            "Same upstream root as TestLookSample.test_sample_rows — "
            "resume_session binds to a new empty lake schema, so run_sql "
            "against typed_<source>__<table> can't find the table. The "
            "LLM repair loop sometimes patches the SQL (which is why "
            "test_basic_count above passes nondeterministically). See "
            "HANDOFF.md in vendor/dataraum-context/."
        ),
        strict=False,
    )
    async def test_columns_metadata(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session,
            "run_sql",
            {"sql": f"SELECT invoice_id, amount FROM {typed('invoices')} LIMIT 3"},
        )
        assert "error" not in result
        assert "columns" in result
        assert "invoice_id" in result["columns"]
        assert "amount" in result["columns"]

    async def test_revenue_order_of_magnitude(self, detection_v1_session: Any) -> None:
        """SQL revenue query returns a result in the right ballpark.

        Injections (outlier_rate, null_ratio) shift amounts, so we only check
        order of magnitude. Financial accuracy is tested by the /deliver skill.
        """
        gt_path = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "data"
            / "detection-v1"
            / "ground_truth.yaml"
        )
        with open(gt_path) as f:
            ground_truth = yaml.safe_load(f)
        expected = ground_truth["annual"]["total_revenue"]
        jl = typed("journal_lines")
        coa = typed("chart_of_accounts")
        result = await call_tool(
            detection_v1_session,
            "run_sql",
            {
                "sql": (
                    f"SELECT SUM(jl.credit) AS total_revenue "
                    f"FROM {jl} jl "
                    f"JOIN {coa} coa ON jl.account_id = coa.account_id "
                    f"WHERE coa.account_type = 'revenue' AND jl.credit > 0"
                )
            },
        )
        assert "error" not in result, f"SQL error: {result.get('error')}"
        actual = result["rows"][0]["total_revenue"]
        assert actual > 0, "Revenue should be positive"
        assert actual > expected * 0.5, f"Revenue too low: {actual:.0f} vs expected {expected:.0f}"
        assert actual < expected * 2.0, f"Revenue too high: {actual:.0f} vs expected {expected:.0f}"


# ---------------------------------------------------------------------------
# query (LLM-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.llm
class TestQuery:
    async def test_revenue_query(self, detection_v1_session: Any) -> None:
        result = await call_tool(
            detection_v1_session,
            "query",
            {"question": "What is the total revenue for fiscal year 2025?"},
        )
        assert "error" not in result, f"Query error: {result.get('error')}"
        assert "answer" in result
        assert "confidence" in result
