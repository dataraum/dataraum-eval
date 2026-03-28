"""Format matrix — pipeline completion per source format (DAT-216).

Tests that the pipeline handles various source formats correctly.
Most tests are blocked on DAT-219 (testdata multi-format fixtures).

The CSV test validates the existing pipeline output (detection-v1 uses CSV).
"""

from __future__ import annotations

import pytest
from dataraum.core.connections import ConnectionManager


class TestCsvFormat:
    """CSV format — validated by existing pipeline output."""

    def test_csv_pipeline_completed(self, tool_manager: ConnectionManager) -> None:
        from dataraum.storage import Table
        from sqlalchemy import select

        with tool_manager.session_scope() as session:
            tables = session.execute(
                select(Table.table_name).where(Table.layer == "typed")
            ).scalars().all()

        assert len(tables) >= 8, f"Expected ≥8 typed tables from CSV, got {len(tables)}"


@pytest.mark.skip(reason="DAT-219: JSON fixtures not yet available")
class TestJsonFormat:
    def test_json_pipeline_completed(self) -> None:
        pass


@pytest.mark.skip(reason="DAT-219: JSONL fixtures not yet available")
class TestJsonlFormat:
    def test_jsonl_pipeline_completed(self) -> None:
        pass


@pytest.mark.skip(reason="DAT-219: directory fixtures not yet available")
class TestDirectoryFormat:
    def test_directory_pipeline_completed(self) -> None:
        pass
