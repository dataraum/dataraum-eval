"""CLI smoke — verify pipeline output structure (DAT-228).

Validates that the existing pipeline output (from `make calibrate`)
has the expected files and tables. Does not re-run the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from dataraum.core.connections import ConnectionManager


class TestOutputStructure:
    def test_metadata_db_exists(self, strategy_output_dir: Path) -> None:
        assert (strategy_output_dir / "metadata.db").exists()

    def test_duckdb_exists(self, strategy_output_dir: Path) -> None:
        assert (strategy_output_dir / "data.duckdb").exists()

    def test_config_dir_exists(self, strategy_output_dir: Path) -> None:
        assert (strategy_output_dir / "config").is_dir()


class TestOutputTables:
    EXPECTED_TABLES = {
        "bank_transactions",
        "chart_of_accounts",
        "fx_rates",
        "invoices",
        "journal_entries",
        "journal_lines",
        "payments",
        "trial_balance",
    }

    def test_has_typed_tables(self, tool_manager: ConnectionManager) -> None:
        from dataraum.storage import Table
        from sqlalchemy import select

        with tool_manager.session_scope() as session:
            tables = session.execute(
                select(Table.table_name).where(Table.layer == "typed")
            ).scalars().all()

        table_set = set(tables)
        for expected in self.EXPECTED_TABLES:
            found = any(t == expected or t.endswith(f"__{expected}") for t in table_set)
            assert found, f"Missing typed table: {expected} (available: {table_set})"

    def test_has_source(self, tool_manager: ConnectionManager) -> None:
        from dataraum.storage import Source
        from sqlalchemy import select

        with tool_manager.session_scope() as session:
            count = session.execute(select(Source)).scalars().all()

        assert len(count) >= 1, "Expected at least one source"
