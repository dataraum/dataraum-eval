"""HTTP MCP client helpers for talking to the dataraum control plane.

Use ``mcp_session`` as an async context manager to get a ready ``ClientSession``
connected to http://127.0.0.1:8000/mcp/ with bearer auth.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from calibration.stack import StackHandle


@asynccontextmanager
async def mcp_session(handle: StackHandle) -> AsyncIterator[ClientSession]:
    """Open an MCP client session against the control plane."""
    async with streamablehttp_client(handle.url, headers=handle.auth_headers()) as (
        read,
        write,
        _get_session_id,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(
    session: ClientSession, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Invoke an MCP tool and return the parsed JSON body.

    The dataraum tools always return a single TextContent with a JSON body.
    """
    result = await session.call_tool(name, arguments or {})
    for content in result.content:
        text = getattr(content, "text", None)
        if text is not None:
            parsed: dict[str, Any] = json.loads(text)
            return parsed
    return {"error": "no text content in response", "raw": str(result)}
