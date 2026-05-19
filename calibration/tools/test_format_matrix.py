"""Format matrix — pipeline completion per source format (DAT-216).

Each non-CSV format runs a full pipeline against its fixture directory via
HTTP MCP and verifies all typed tables come back from ``look()``. CSV is
covered by the ambient ``detection_v1_session`` fixture (same code path).

JSON / JSONL / Parquet / mixed-format tests are ``@pytest.mark.slow`` —
each spins up a fresh pipeline (~6 min).
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.mcp_client import call_tool, mcp_session
from calibration.stack import StackHandle, container_path_for

EXPECTED_TABLE_COUNT = 8


async def _typed_table_names(session: Any) -> set[str]:
    """Return the set of bare typed table names from look()."""
    result = await call_tool(session, "look", {})
    names = set()
    for t in result.get("tables", []):
        n = t.get("name", "")
        names.add(n.split("__", 1)[1] if "__" in n else n)
    return names


class TestCsvFormat:
    """CSV format — validated via the ambient detection-v1 pipeline."""

    async def test_csv_pipeline_completed(self, detection_v1_session: Any) -> None:
        names = await _typed_table_names(detection_v1_session)
        assert len(names) >= EXPECTED_TABLE_COUNT, (
            f"Expected ≥{EXPECTED_TABLE_COUNT} typed tables from CSV, got {len(names)}: {names}"
        )


async def _run_format_pipeline(strategy: str) -> int:
    """End-to-end MCP run for a non-default strategy; return typed table count.

    Each test owns its own MCP session (a fresh client per pipeline run) so
    state doesn't leak between formats.
    """
    handle: StackHandle = runner_mod.up()
    # Ensure the strategy dir exists in our mounted sources tree
    container_path = container_path_for(strategy)
    async with mcp_session(handle) as s:
        await runner_mod._end_active_session_if_any(s)
        await runner_mod._ensure_source_registered(s, _safe_name(strategy), container_path)
        begin = await call_tool(
            s,
            "begin_session",
            {
                "source": _safe_name(strategy),
                "intent": f"format_matrix:{strategy}",
                "contract": "aggregation_safe",
                "vertical": "finance",
            },
        )
        if "error" in begin:
            pytest.fail(f"begin_session({strategy!r}) failed: {begin}")
        final = await runner_mod._wait_for_pipeline(s)
        if "error" in final:
            pytest.fail(f"Pipeline for {strategy!r} failed: {final}")
        names = await _typed_table_names(s)
        return len(names)


def _safe_name(strategy: str) -> str:
    """add_source accepts ^[a-z][a-z0-9_]{1,48}$ — normalize the strategy."""
    return strategy.replace("-", "_")


@pytest.mark.slow
class TestJsonFormat:
    async def test_json_pipeline_completed(self) -> None:
        count = await _run_format_pipeline("clean-json")
        assert count >= EXPECTED_TABLE_COUNT, (
            f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"
        )


@pytest.mark.slow
class TestJsonlFormat:
    async def test_jsonl_pipeline_completed(self) -> None:
        count = await _run_format_pipeline("clean-jsonl")
        assert count >= EXPECTED_TABLE_COUNT, (
            f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"
        )


@pytest.mark.slow
class TestParquetFormat:
    async def test_parquet_pipeline_completed(self) -> None:
        count = await _run_format_pipeline("clean-parquet")
        assert count >= EXPECTED_TABLE_COUNT, (
            f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"
        )


@pytest.mark.slow
class TestMixedDirectoryFormat:
    """Mixed-format directory — CSV, JSON, and Parquet files in one folder."""

    async def test_mixed_directory_pipeline_completed(self) -> None:
        count = await _run_format_pipeline("clean_mixed")
        assert count >= EXPECTED_TABLE_COUNT, (
            f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"
        )
