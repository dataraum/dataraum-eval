"""Format matrix — pipeline completion per source format (DAT-216).

Tests that the pipeline handles various source formats correctly.
Each format test generates clean data, runs the pipeline, and verifies
typed tables exist in the output.

CSV is validated by the existing calibration output (fast).
JSON, JSONL, Parquet run full pipelines (slow, marked @pytest.mark.slow).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dataraum.core.connections import ConnectionManager

EVAL_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"

EXPECTED_TABLE_COUNT = 8


class TestCsvFormat:
    """CSV format — validated by existing pipeline output."""

    def test_csv_pipeline_completed(self, tool_manager: ConnectionManager) -> None:
        from dataraum.storage import Table
        from sqlalchemy import select

        with tool_manager.session_scope() as session:
            tables = session.execute(
                select(Table.table_name).where(Table.layer == "typed")
            ).scalars().all()

        assert len(tables) >= EXPECTED_TABLE_COUNT, (
            f"Expected ≥{EXPECTED_TABLE_COUNT} typed tables from CSV, got {len(tables)}"
        )


def _run_format_pipeline(data_dir: Path, output_dir: Path) -> int:
    """Run pipeline on a data directory and return typed table count."""
    from dataraum.core.connections import ConnectionConfig
    from dataraum.core.connections import ConnectionManager as CM
    from dataraum.pipeline.runner import RunConfig
    from dataraum.pipeline.runner import run as pipeline_run
    from dataraum.storage import Table
    from sqlalchemy import select

    if not data_dir.exists():
        pytest.skip(f"No fixture data at {data_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    config = RunConfig(source_path=data_dir, output_dir=output_dir, contract="aggregation_safe")
    result = pipeline_run(config)
    assert result.success, f"Pipeline failed: {result.error}"

    mgr = CM(ConnectionConfig.for_directory(output_dir))
    mgr.initialize()
    try:
        with mgr.session_scope() as session:
            count = len(
                session.execute(
                    select(Table.table_name).where(Table.layer == "typed")
                ).scalars().all()
            )
    finally:
        mgr.close()
    return count


@pytest.mark.slow
class TestJsonFormat:
    def test_json_pipeline_completed(self, tmp_path: Path) -> None:
        count = _run_format_pipeline(DATA_DIR / "clean-json", tmp_path / "output")
        assert count >= EXPECTED_TABLE_COUNT, f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"


@pytest.mark.slow
class TestJsonlFormat:
    def test_jsonl_pipeline_completed(self, tmp_path: Path) -> None:
        count = _run_format_pipeline(DATA_DIR / "clean-jsonl", tmp_path / "output")
        assert count >= EXPECTED_TABLE_COUNT, f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"


@pytest.mark.slow
class TestParquetFormat:
    def test_parquet_pipeline_completed(self, tmp_path: Path) -> None:
        count = _run_format_pipeline(DATA_DIR / "clean-parquet", tmp_path / "output")
        assert count >= EXPECTED_TABLE_COUNT, f"Expected ≥{EXPECTED_TABLE_COUNT} tables, got {count}"
