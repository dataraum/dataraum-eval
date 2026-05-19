"""HTTP MCP client helpers for talking to the dataraum control plane.

Use ``mcp_session`` as an async context manager to get a ready ``ClientSession``
connected to http://127.0.0.1:8000/mcp/ with bearer auth.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from calibration.stack import StackHandle


@asynccontextmanager
async def mcp_session(handle: StackHandle) -> AsyncIterator[ClientSession]:
    """Open an MCP client session against the control plane.

    The streamable_http_client opens internal anyio task groups; pytest-asyncio
    teardown closes async fixtures in a different task than the open, which
    anyio (correctly) flags. We catch that specific ``RuntimeError`` on exit
    so a clean test produces a clean exit — the work has already happened by
    the time teardown runs.
    """
    try:
        async with httpx.AsyncClient(headers=handle.auth_headers()) as http_client:
            async with streamable_http_client(handle.url, http_client=http_client) as (
                read,
                write,
                _get_session_id,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
    except RuntimeError as exc:
        if "different task" not in str(exc):
            raise


async def call_tool(
    session: ClientSession, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Invoke an MCP tool and return the parsed JSON body.

    The dataraum tools always return a single TextContent with a JSON body.
    Schema-level errors (e.g. enum-validation rejections on inputSchema) can
    bypass the handler and yield empty or non-JSON content; surface those
    as a structured error dict so callers don't have to handle ValueError.
    """
    result = await session.call_tool(name, arguments or {})
    for content in result.content:
        text = getattr(content, "text", None)
        if text is None:
            continue
        if not text.strip():
            return {"error": "empty response text", "isError": bool(getattr(result, "isError", False))}
        try:
            parsed: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            return {"error": "non-JSON response text", "raw": text}
        return parsed
    return {"error": "no text content in response", "raw": str(result)}
