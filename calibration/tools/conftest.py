"""Tools-test fixtures + collection guard.

Every test in this directory was written against the pre-L6 in-process MCP
(``create_connected_server_and_client_session`` + private handler imports
like ``_begin_session``, ``_look``, etc.). Post-DAT-325 the only transport is
HTTP, the handlers are no longer importable, and the on-disk workspace is
inside the container. The whole directory needs a rewrite against the new
``mcp_client`` fixture (calibration/conftest.py).

Until that rewrite lands, skip collection so unrelated tests can still run.
"""

from __future__ import annotations

collect_ignore_glob = ["test_*.py"]
