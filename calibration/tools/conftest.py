"""Tools-test fixtures.

All tools tests drive the dataraum control plane over HTTP MCP via the
``mcp_client`` fixture (calibration/conftest.py). This module adds a
small helper that attaches each test to the ``detection-v1`` source — by
resuming the most recent archived session when one exists, otherwise by
running a fresh pipeline.

Why resume instead of always begin+measure:
DAT-323 gives each ``begin_session`` a brand-new lake schema. Pipeline
data lives in the schema that wrote it, but entropy scores live in
workspace Postgres. So a fresh begin_session sees "pipeline already
ran" (scores exist in workspace) and skips re-running, leaving the new
session's lake schema empty — every ``look(sample=N)`` and ``run_sql``
then errors with "table not found in lake.session_<new id>". Resuming
the schema that holds the data avoids the entire 6 min pipeline rerun
between tests too.

Tests not yet ported to the HTTP MCP client are still skipped via
``collect_ignore_glob`` — drop a file's pattern from the list once it's
ported.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.mcp_client import call_tool

collect_ignore_glob = [
    "test_adhoc_teach_loop.py",
]


async def _most_recent_archive_for(client: Any, source: str) -> str | None:
    """Return the most-recently-ended session_id bound to ``source`` (or None)."""
    listing = await call_tool(client, "resume_session", {})
    archives = listing.get("archived_sessions", [])
    matches = [a for a in archives if a.get("source") == source]
    if not matches:
        return None
    matches.sort(key=lambda a: a.get("ended_at", ""), reverse=True)
    return str(matches[0]["session_id"])


@pytest.fixture
async def detection_v1_session(mcp_client: Any) -> Any:
    """Ensure an active session bound to detection_v1 with populated pipeline data.

    Reuses a prior session schema when one is archived for this source —
    that's where the typed/raw DuckLake tables actually live. Falls back to
    a fresh pipeline run when no archive exists.
    """
    source = "detection_v1"
    await end_active_session(mcp_client)

    archive_id = await _most_recent_archive_for(mcp_client, source)
    if archive_id is not None:
        result = await call_tool(
            mcp_client,
            "resume_session",
            {"session_id": archive_id, "intent": "tools-test reuse"},
        )
        if "error" not in result:
            return mcp_client
        # Resume failed (stale archive, schema gone, etc.) — fall through.

    # No archive (or resume failed) — run a fresh pipeline.
    await runner_mod.setup_strategy(mcp_client, "detection-v1")
    final = await runner_mod._wait_for_pipeline(mcp_client)
    if "error" in final:
        pytest.fail(f"Pipeline failed during setup: {final}")
    return mcp_client


async def end_active_session(client: Any) -> None:
    """Idempotent: end any active session so the next test can begin fresh."""
    await call_tool(client, "end_session", {"outcome": "abandoned"})
