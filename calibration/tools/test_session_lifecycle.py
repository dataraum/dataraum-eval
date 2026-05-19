"""Session lifecycle — flow enforcement and state shape via HTTP MCP.

Exercises begin / end / resume semantics and the "sources sealed during
session" guard. State lives in the container Postgres; each test resets to
a known state via ``end_active_session`` before it begins.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.mcp_client import call_tool
from calibration.stack import container_path_for

from .conftest import end_active_session

SOURCE_NAME = "detection_v1"
SOURCE_PATH = container_path_for("detection-v1")


async def _ensure_clean(client: Any) -> None:
    """End any active session and ensure detection_v1 is registered."""
    await end_active_session(client)
    await runner_mod._ensure_source_registered(client, SOURCE_NAME, SOURCE_PATH)


# ---------------------------------------------------------------------------
# Begin / end cycle
# ---------------------------------------------------------------------------


class TestBeginEndCycle:
    async def test_begin_returns_source(self, mcp_client: Any) -> None:
        await _ensure_clean(mcp_client)
        result = await call_tool(
            mcp_client,
            "begin_session",
            {"source": SOURCE_NAME, "intent": "lifecycle test"},
        )
        assert "error" not in result, f"begin_session error: {result.get('error')}"
        assert result.get("source") == SOURCE_NAME, (
            f"Expected source={SOURCE_NAME!r} (post-DAT-290 scalar), got {result.get('source')!r}"
        )

    async def test_begin_end_delivered(self, mcp_client: Any) -> None:
        await _ensure_clean(mcp_client)
        begin = await call_tool(
            mcp_client,
            "begin_session",
            {"source": SOURCE_NAME, "intent": "lifecycle test"},
        )
        assert "error" not in begin

        end = await call_tool(
            mcp_client,
            "end_session",
            {"outcome": "delivered", "summary": "test completed"},
        )
        assert "error" not in end, f"end_session error: {end.get('error')}"
        assert end.get("outcome") == "delivered"
        assert "duration_seconds" in end

    async def test_begin_after_end(self, mcp_client: Any) -> None:
        """After ending, a new session can be started against the same source."""
        await _ensure_clean(mcp_client)
        await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "first"}
        )
        await call_tool(mcp_client, "end_session", {"outcome": "delivered"})

        result2 = await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "second"}
        )
        assert "error" not in result2, f"Second begin_session error: {result2.get('error')}"
        assert result2.get("source") == SOURCE_NAME


# ---------------------------------------------------------------------------
# Flow enforcement
# ---------------------------------------------------------------------------


class TestFlowEnforcement:
    async def test_sources_sealed_during_session(self, mcp_client: Any) -> None:
        await _ensure_clean(mcp_client)
        await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "test"}
        )
        # Try to add a new source while session is active
        result = await call_tool(
            mcp_client,
            "add_source",
            {"name": "should_be_sealed", "path": "/var/lib/dataraum/sources/detection-v1"},
        )
        assert "error" in result
        assert "sealed" in result["error"].lower()

    async def test_end_without_session(self, mcp_client: Any) -> None:
        await end_active_session(mcp_client)
        # Calling end again with no active session
        result = await call_tool(mcp_client, "end_session", {"outcome": "delivered"})
        assert "error" in result


# ---------------------------------------------------------------------------
# End session outcomes
# ---------------------------------------------------------------------------


class TestEndSessionOutcomes:
    @pytest.mark.parametrize("outcome", ["delivered", "refused", "abandoned", "escalated"])
    async def test_valid_outcome(self, mcp_client: Any, outcome: str) -> None:
        await _ensure_clean(mcp_client)
        await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "test"}
        )
        end = await call_tool(mcp_client, "end_session", {"outcome": outcome})
        assert "error" not in end, f"end_session error: {end.get('error')}"
        assert end.get("outcome") == outcome

    async def test_invalid_outcome(self, mcp_client: Any) -> None:
        await _ensure_clean(mcp_client)
        await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "test"}
        )
        end = await call_tool(mcp_client, "end_session", {"outcome": "invalid_xyz"})
        assert "error" in end


# ---------------------------------------------------------------------------
# Idempotent begin (resume-when-active)
# ---------------------------------------------------------------------------


class TestIdempotentBegin:
    async def test_begin_while_active_orients(self, mcp_client: Any) -> None:
        """Calling begin_session while one is active resumes it (DAT-290 behavior)."""
        await _ensure_clean(mcp_client)
        first = await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "first"}
        )
        assert "error" not in first

        second = await call_tool(
            mcp_client, "begin_session", {"source": SOURCE_NAME, "intent": "second"}
        )
        # Should not error — should re-orient to the active session.
        assert "error" not in second
        assert second.get("source") == SOURCE_NAME
