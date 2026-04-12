"""Shared fixtures for MCP tool-level tests.

tool_manager, db_session, duckdb_cursor, and typed_tables are defined
in the parent conftest (calibration/conftest.py). This file adds
tool-specific fixtures.

Prerequisites: pipeline output in output/{strategy}/ (run `make calibrate`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from dataraum.core.connections import ConnectionManager
from mcp.client.session import ClientSession


@pytest.fixture(scope="session")
def source_id(tool_manager: ConnectionManager) -> str:
    """The pipeline source_id from the output database."""
    from dataraum.storage import Source
    from sqlalchemy import select

    with tool_manager.session_scope() as session:
        source = session.execute(select(Source)).scalars().first()
        if not source:
            pytest.skip("No source in pipeline output")
        return source.source_id


@pytest.fixture(scope="session")
def known_tables(tool_manager: ConnectionManager) -> list[str]:
    """Table names in pipeline output (typed layer)."""
    from dataraum.storage import Table
    from sqlalchemy import select

    with tool_manager.session_scope() as session:
        tables = session.execute(
            select(Table.table_name).where(Table.layer == "typed")
        ).scalars().all()
        return list(tables)


# ---------------------------------------------------------------------------
# MCP client fixture — in-memory server for full call_tool dispatch
# ---------------------------------------------------------------------------


async def _call_tool(client: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and return the parsed JSON response."""
    result = await client.call_tool(name, arguments)
    for content in result.content:
        if hasattr(content, "text"):
            return json.loads(content.text)
    return {"error": "No text content in response"}


@pytest.fixture(scope="module")
async def mcp_client(strategy_output_dir: Path) -> AsyncGenerator[ClientSession]:
    """In-memory MCP client connected to a DataRaum server.

    Uses the strategy pipeline output as the server workspace.
    Yields a ClientSession that can call tools through the full
    MCP dispatch (state management, session lifecycle, pipeline triggers).
    """
    from dataraum.mcp.server import create_server
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(output_dir=strategy_output_dir)

    async with create_connected_server_and_client_session(server) as client:
        yield client
