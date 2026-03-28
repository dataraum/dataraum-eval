"""Shared fixtures for MCP tool-level tests.

tool_manager, db_session, duckdb_cursor, and typed_tables are defined
in the parent conftest (calibration/conftest.py). This file adds
tool-specific fixtures.

Prerequisites: pipeline output in output/{strategy}/ (run `make calibrate`).
"""

from __future__ import annotations

import pytest
from dataraum.core.connections import ConnectionManager


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
