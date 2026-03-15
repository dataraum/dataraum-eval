"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and pipeline output for assertions.
Strategy is configurable via --strategy flag (default: zone1-detection-v1).
"""

from __future__ import annotations

import json
import sqlite3
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
        return yaml.safe_load(f)


@dataclass
class GateScores:
    """Gate scores from PhaseLog, split by detector scope."""

    # Column-scoped: (table, column, detector_id) → score
    column: dict[tuple[str, str, str], float] = field(default_factory=dict)
    # Table-scoped: (table, detector_id) → score
    table: dict[tuple[str, str], float] = field(default_factory=dict)
    # View-scoped: (view_name, detector_id) → score
    view: dict[tuple[str, str], float] = field(default_factory=dict)


def _load_gate_scores(db_path: Path) -> GateScores:
    """Load detector scores from gate measurement persisted in PhaseLog.

    Tries analysis_review (Gate 2) first — it has all detectors (Zone 1 + Zone 2).
    Falls back to quality_review (Gate 1) which has Zone 1 detectors only.
    """
    if not db_path.exists():
        pytest.skip(f"No pipeline output at {db_path} — run pipeline first")

    conn = sqlite3.connect(str(db_path))
    try:
        # Try analysis_review first (Gate 2 — Zone 1 + Zone 2 scores)
        row = None
        for gate in ("analysis_review", "quality_review"):
            row = conn.execute(
                "SELECT outputs FROM phase_logs "
                f"WHERE phase_name = '{gate}' "
                "ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            if row is not None and row[0] is not None:
                break
    except sqlite3.OperationalError:
        pytest.skip("phase_logs table not found in metadata.db")
    finally:
        conn.close()

    if row is None or row[0] is None:
        pytest.skip("No quality_review/analysis_review phase log found — run pipeline first")

    outputs = json.loads(row[0]) if isinstance(row[0], str) else row[0]

    # Map dimension_path → detector_id (e.g. "value.distribution.benford_compliance" → "benford")
    id_map = outputs.get("detector_id_map", {})
    result = GateScores()

    # Column-scoped scores
    column_details = outputs.get("gate_column_details", {})
    for dim_path, targets in column_details.items():
        detector_id = id_map.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            # target: "column:table_name.column_name"
            ref = target.removeprefix("column:")
            parts = ref.split(".", 1)
            if len(parts) == 2:
                table, column = parts
                key = (table, column, detector_id)
                if key not in result.column or score > result.column[key]:
                    result.column[key] = score

    # Table-scoped scores
    table_details = outputs.get("gate_table_details", {})
    for dim_path, targets in table_details.items():
        detector_id = id_map.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            # target: "table:table_name"
            table = target.removeprefix("table:")
            key = (table, detector_id)
            if key not in result.table or score > result.table[key]:
                result.table[key] = score

    # View-scoped scores
    view_details = outputs.get("gate_view_details", {})
    for dim_path, targets in view_details.items():
        detector_id = id_map.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            # target: "view:view_name"
            view_name = target.removeprefix("view:")
            key = (view_name, detector_id)
            if key not in result.view or score > result.view[key]:
                result.view[key] = score

    return result


# ---------------------------------------------------------------------------
# Strategy-aware fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def strategy_name(request: pytest.FixtureRequest) -> str:
    """The strategy being tested."""
    return request.config.getoption("--strategy")


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
    return entropy_map.get("injections", [])


@pytest.fixture(scope="session")
def gate_scores(strategy_output_dir: Path) -> GateScores:
    """All detector scores from gate measurement for the current strategy."""
    return _load_gate_scores(strategy_output_dir / "metadata.db")


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
def post_fix_scores(fixed_output_dir: Path) -> dict[tuple[str, str, str], float]:
    """Detector scores after fix application (column-scoped)."""
    return _load_gate_scores(fixed_output_dir / "metadata.db").column


# ---------------------------------------------------------------------------
# Clean baseline (always uses "clean" strategy data)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def clean_gate_scores() -> GateScores:
    """All detector scores from clean pipeline output (no injections)."""
    return _load_gate_scores(OUTPUT_DIR / "clean" / "metadata.db")


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
