"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and pipeline output for assertions.
Strategy is configurable via --strategy flag (default: zone1-detection-v1).
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
        default="zone1-detection-v1",
        help="Strategy name to test against (default: zone1-detection-v1)",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        result: dict[str, Any] = yaml.safe_load(f)
    return result


@dataclass
class GateScores:
    """Detector scores from measure_entropy(), split by scope."""

    # Column-scoped: (table, column, detector_id) → score
    column: dict[tuple[str, str, str], float] = field(default_factory=dict)
    # Table-scoped: (table, detector_id) → score
    table: dict[tuple[str, str], float] = field(default_factory=dict)
    # View-scoped: (view_name, detector_id) → score
    view: dict[tuple[str, str], float] = field(default_factory=dict)


def _load_gate_scores(output_dir: Path) -> GateScores:
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

    result = GateScores()

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
def gate_scores(strategy_output_dir: Path) -> GateScores:
    """All detector scores from measure_entropy() for the current strategy."""
    return _load_gate_scores(strategy_output_dir)


@pytest.fixture(scope="session")
def pipeline_scores(gate_scores: GateScores) -> dict[tuple[str, str, str], float]:
    """Column-scoped detector scores (backwards compatible)."""
    return gate_scores.column


@pytest.fixture(scope="session")
def pipeline_table_scores(gate_scores: GateScores) -> dict[tuple[str, str], float]:
    """Table-scoped detector scores: (table, detector_id) → score."""
    return gate_scores.table


@pytest.fixture(scope="session")
def pipeline_view_scores(gate_scores: GateScores) -> dict[tuple[str, str], float]:
    """View-scoped detector scores: (view_name, detector_id) → score."""
    return gate_scores.view


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
def post_fix_gate_scores(fixed_output_dir: Path) -> GateScores:
    """All detector scores after fix application."""
    return _load_gate_scores(fixed_output_dir)


@pytest.fixture(scope="session")
def post_fix_scores(post_fix_gate_scores: GateScores) -> dict[tuple[str, str, str], float]:
    """Detector scores after fix application (column-scoped)."""
    return post_fix_gate_scores.column


@pytest.fixture(scope="session")
def post_fix_table_scores(post_fix_gate_scores: GateScores) -> dict[tuple[str, str], float]:
    """Detector scores after fix application (table-scoped)."""
    return post_fix_gate_scores.table


# ---------------------------------------------------------------------------
# Clean baseline (always uses "clean" strategy data)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def clean_gate_scores() -> GateScores:
    """All detector scores from clean pipeline output (no injections)."""
    return _load_gate_scores(OUTPUT_DIR / "clean")


@pytest.fixture(scope="session")
def clean_pipeline_scores(clean_gate_scores: GateScores) -> dict[tuple[str, str, str], float]:
    """Clean column-scoped scores (backwards compatible)."""
    return clean_gate_scores.column


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
