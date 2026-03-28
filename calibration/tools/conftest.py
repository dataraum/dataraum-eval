"""Shared fixtures for MCP tool-level tests.

Provides ConnectionManager, SQLAlchemy session, and DuckDB cursor
pointing at the calibration pipeline output. All session-scoped
fixtures avoid re-initializing connections per test.

Prerequisites: pipeline output in output/{strategy}/ (run `make calibrate`).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from dataraum.core.config import set_config_root
from dataraum.core.connections import ConnectionConfig, ConnectionManager


@pytest.fixture(scope="session")
def tool_manager(strategy_output_dir: Path) -> Generator[ConnectionManager]:
    """Session-scoped ConnectionManager for tool tests."""
    db_path = strategy_output_dir / "metadata.db"
    if not db_path.exists():
        pytest.skip(f"No pipeline output at {db_path} -- run 'make calibrate' first")

    config_root = strategy_output_dir / "config"
    if config_root.exists():
        set_config_root(config_root)

    config = ConnectionConfig.for_directory(strategy_output_dir)
    manager = ConnectionManager(config)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def db_session(tool_manager: ConnectionManager) -> Generator[Any]:
    """Function-scoped SQLAlchemy session."""
    with tool_manager.session_scope() as session:
        yield session


@pytest.fixture
def duckdb_cursor(tool_manager: ConnectionManager) -> Generator[Any]:
    """Function-scoped DuckDB cursor."""
    with tool_manager.duckdb_cursor() as cursor:
        yield cursor


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
