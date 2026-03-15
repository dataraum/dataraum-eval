"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and pipeline output for assertions.
Strategy is configurable via --strategy flag (default: zone1-detection-v1).
"""

from __future__ import annotations

import json
import sqlite3
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


def _load_gate_scores(db_path: Path) -> dict[tuple[str, str, str], float]:
    """Load detector scores from gate measurement persisted in PhaseLog.

    Tries analysis_review (Gate 2) first — it has all detectors (Zone 1 + Zone 2).
    Falls back to quality_review (Gate 1) which has Zone 1 detectors only.
    Returns dict of (table, column, detector_id) -> score.
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
    column_details = outputs.get("gate_column_details")
    if column_details is None:
        pytest.skip("No gate_column_details in quality_review outputs — pipeline may need re-run")

    # Map dimension_path → detector_id (e.g. "value.distribution.benford_compliance" → "benford")
    id_map = outputs.get("detector_id_map", {})

    scores: dict[tuple[str, str, str], float] = {}
    for dim_path, targets in column_details.items():
        detector_id = id_map.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            # target: "column:table_name.column_name"
            ref = target.removeprefix("column:")
            parts = ref.split(".", 1)
            if len(parts) == 2:
                table, column = parts
                key = (table, column, detector_id)
                # Keep highest score if multiple entries exist
                if key not in scores or score > scores[key]:
                    scores[key] = score

    return scores


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
def pipeline_scores(strategy_output_dir: Path) -> dict[tuple[str, str, str], float]:
    """Detector scores from gate measurement for the current strategy."""
    return _load_gate_scores(strategy_output_dir / "metadata.db")


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
    """Detector scores after fix application."""
    return _load_gate_scores(fixed_output_dir / "metadata.db")


# ---------------------------------------------------------------------------
# Clean baseline (always uses "clean" strategy data)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def clean_pipeline_scores() -> dict[tuple[str, str, str], float]:
    """Detector scores from clean pipeline output (no injections)."""
    return _load_gate_scores(OUTPUT_DIR / "clean" / "metadata.db")


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
