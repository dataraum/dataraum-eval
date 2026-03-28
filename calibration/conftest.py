"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and pipeline output for assertions.
Strategy is configurable via --strategy flag (default: detection-v1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

EVAL_ROOT = Path(__file__).parent.parent
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--strategy",
        default="detection-v1",
        help="Strategy name to test against (default: detection-v1)",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        result: dict[str, Any] = yaml.safe_load(f)
    return result


@dataclass
class DetectorScores:
    """Detector scores from measure_entropy(), split by scope."""

    # Column-scoped: (table, column, detector_id) → score
    column: dict[tuple[str, str, str], float] = field(default_factory=dict)
    # Table-scoped: (table, detector_id) → score
    table: dict[tuple[str, str], float] = field(default_factory=dict)
    # View-scoped: (view_name, detector_id) → score
    view: dict[tuple[str, str], float] = field(default_factory=dict)


def _load_scores(output_dir: Path) -> DetectorScores:
    """Load detector scores via measure_entropy().

    Opens the pipeline output database, resolves the source, and calls
    measure_entropy() to aggregate EntropyObjectRecord rows into scores.
    """
    db_path = output_dir / "metadata.db"
    if not db_path.exists():
        pytest.skip(f"No pipeline output at {db_path} — run pipeline first")

    from dataraum.core.config import set_config_root
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.detectors.base import get_default_registry
    from dataraum.entropy.measurement import measure_entropy
    from dataraum.storage import Source
    from sqlalchemy import select

    config_root = output_dir / "config"
    if config_root.exists():
        set_config_root(config_root)

    manager = ConnectionManager(ConnectionConfig.for_directory(output_dir))
    manager.initialize()

    try:
        with manager.session_scope() as session:
            source = session.execute(select(Source)).scalars().first()
            if not source:
                pytest.skip("No source found in output database")

            registry = get_default_registry()
            detector_ids = registry.get_detector_ids()

            measurement = measure_entropy(session, source.source_id, detector_ids)
    finally:
        manager.close()

    result = DetectorScores()

    def _strip_source_prefix(name: str) -> str:
        """Strip source_name__ prefix from table names (e.g. detection_v1__invoices → invoices)."""
        if "__" in name:
            return name.split("__", 1)[1]
        return name

    # Column-scoped scores
    for dim_path, targets in measurement.column_details.items():
        detector_id = dim_path.rsplit(".", 1)[-1]
        # Look up detector_id from registry by dimension_path
        for det in registry.get_all_detectors():
            if det.dimension_path == dim_path:
                detector_id = det.detector_id
                break
        for target, score in targets.items():
            ref = target.removeprefix("column:")
            parts = ref.split(".", 1)
            if len(parts) == 2:
                table, column = parts
                table = _strip_source_prefix(table)
                key = (table, column, detector_id)
                if key not in result.column or score > result.column[key]:
                    result.column[key] = score

    # Table-scoped scores
    for dim_path, targets in measurement.table_details.items():
        detector_id = dim_path.rsplit(".", 1)[-1]
        for det in registry.get_all_detectors():
            if det.dimension_path == dim_path:
                detector_id = det.detector_id
                break
        for target, score in targets.items():
            tbl = target.removeprefix("table:")
            tbl = _strip_source_prefix(tbl)
            tbl_key = (tbl, detector_id)
            if tbl_key not in result.table or score > result.table[tbl_key]:
                result.table[tbl_key] = score

    # View-scoped scores
    for dim_path, targets in measurement.view_details.items():
        detector_id = dim_path.rsplit(".", 1)[-1]
        for det in registry.get_all_detectors():
            if det.dimension_path == dim_path:
                detector_id = det.detector_id
                break
        for target, score in targets.items():
            vw = target.removeprefix("view:")
            vw_key = (vw, detector_id)
            if vw_key not in result.view or score > result.view[vw_key]:
                result.view[vw_key] = score

    return result


# ---------------------------------------------------------------------------
# Strategy-aware fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def strategy_name(request: pytest.FixtureRequest) -> str:
    """The strategy being tested."""
    name: str = request.config.getoption("--strategy")
    return name


@pytest.fixture(scope="session")
def strategy_data_dir(strategy_name: str) -> Path:
    """Path to generated test data for the current strategy."""
    path = DATA_DIR / strategy_name
    if not path.exists():
        pytest.skip(
            f"No test data at {path}. "
            f"Run: uv run python -m calibration.runner {strategy_name} --generate-only"
        )
    return path


@pytest.fixture(scope="session")
def strategy_output_dir(strategy_name: str) -> Path:
    """Path to pipeline output for the current strategy."""
    path = OUTPUT_DIR / strategy_name
    if not path.exists():
        pytest.skip(
            f"No pipeline output at {path}. "
            f"Run: uv run python -m calibration.runner {strategy_name}"
        )
    return path


@pytest.fixture(scope="session")
def entropy_map(strategy_data_dir: Path) -> dict[str, Any]:
    """Load entropy_map.yaml from test data."""
    path = strategy_data_dir / "entropy_map.yaml"
    if not path.exists():
        pytest.skip(f"No entropy_map at {path}")
    return _load_yaml(path)


@pytest.fixture(scope="session")
def ground_truth(strategy_data_dir: Path) -> dict[str, Any]:
    """Load ground_truth.yaml from test data."""
    path = strategy_data_dir / "ground_truth.yaml"
    if not path.exists():
        pytest.skip(f"No ground_truth at {path}")
    return _load_yaml(path)


@pytest.fixture(scope="session")
def injections(entropy_map: dict[str, Any]) -> list[dict[str, Any]]:
    """List of injection dicts from entropy_map."""
    result: list[dict[str, Any]] = entropy_map.get("injections", [])
    return result


@pytest.fixture(scope="session")
def detector_scores(strategy_output_dir: Path) -> DetectorScores:
    """All detector scores from measure_entropy() for the current strategy."""
    return _load_scores(strategy_output_dir)


@pytest.fixture(scope="session")
def pipeline_scores(detector_scores: DetectorScores) -> dict[tuple[str, str, str], float]:
    """Column-scoped detector scores (backwards compatible)."""
    return detector_scores.column


@pytest.fixture(scope="session")
def pipeline_table_scores(detector_scores: DetectorScores) -> dict[tuple[str, str], float]:
    """Table-scoped detector scores: (table, detector_id) → score."""
    return detector_scores.table


@pytest.fixture(scope="session")
def pipeline_view_scores(detector_scores: DetectorScores) -> dict[tuple[str, str], float]:
    """View-scoped detector scores: (view_name, detector_id) → score."""
    return detector_scores.view


# ---------------------------------------------------------------------------
# MCP tool fixtures (shared across calibration/ and calibration/tools/)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def tool_manager(strategy_output_dir: Path) -> Any:
    """Session-scoped ConnectionManager for MCP tool tests."""

    from dataraum.core.config import set_config_root
    from dataraum.core.connections import ConnectionConfig, ConnectionManager

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
def db_session(tool_manager: Any) -> Any:
    """Function-scoped SQLAlchemy session."""
    with tool_manager.session_scope() as session:
        yield session


@pytest.fixture
def duckdb_cursor(tool_manager: Any) -> Any:
    """Function-scoped DuckDB cursor."""
    with tool_manager.duckdb_cursor() as cursor:
        yield cursor


@pytest.fixture(scope="session")
def typed_tables(tool_manager: Any) -> dict[str, str]:
    """Map short table names to DuckDB typed view names.

    Pipeline prefixes tables with source_name (e.g. ``detection_v1__invoices``).
    This maps the short suffix (``invoices``) to the full DuckDB view name.
    """
    from dataraum.storage import Table
    from sqlalchemy import select

    with tool_manager.session_scope() as session:
        table_names = list(
            session.execute(
                select(Table.table_name).where(Table.layer == "typed")
            ).scalars().all()
        )

    mapping: dict[str, str] = {}
    for full_name in table_names:
        short = full_name.rsplit("__", 1)[-1] if "__" in full_name else full_name
        mapping[short] = f"typed_{full_name}"
    return mapping


# ---------------------------------------------------------------------------
# Fix calibration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fixed_output_dir(strategy_name: str) -> Path:
    """Path to fixed pipeline output."""
    path = OUTPUT_DIR / f"{strategy_name}-fixed"
    if not path.exists():
        pytest.skip(
            f"No fixed output at {path}. "
            f"Run: make fix-{strategy_name}"
        )
    return path


@pytest.fixture(scope="session")
def post_fix_detector_scores(fixed_output_dir: Path) -> DetectorScores:
    """All detector scores after fix application."""
    return _load_scores(fixed_output_dir)


@pytest.fixture(scope="session")
def post_fix_scores(post_fix_detector_scores: DetectorScores) -> dict[tuple[str, str, str], float]:
    """Detector scores after fix application (column-scoped)."""
    return post_fix_detector_scores.column


@pytest.fixture(scope="session")
def post_fix_table_scores(post_fix_detector_scores: DetectorScores) -> dict[tuple[str, str], float]:
    """Detector scores after fix application (table-scoped)."""
    return post_fix_detector_scores.table


# ---------------------------------------------------------------------------
# Clean baseline (always uses "clean" strategy data)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def clean_detector_scores() -> DetectorScores:
    """All detector scores from clean pipeline output (no injections)."""
    return _load_scores(OUTPUT_DIR / "clean")


@pytest.fixture(scope="session")
def clean_pipeline_scores(clean_detector_scores: DetectorScores) -> dict[tuple[str, str, str], float]:
    """Clean column-scoped scores (backwards compatible)."""
    return clean_detector_scores.column


@pytest.fixture(scope="session")
def score_deltas(
    pipeline_scores: dict[tuple[str, str, str], float],
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> dict[tuple[str, str, str], float]:
    """Delta between injected and clean scores (injected - clean).

    A positive delta means the injection raised the score.
    Keys present in injected but not clean use the raw injected score.
    """
    deltas: dict[tuple[str, str, str], float] = {}
    for key, injected_score in pipeline_scores.items():
        clean_score = clean_pipeline_scores.get(key, 0.0)
        deltas[key] = injected_score - clean_score
    return deltas
