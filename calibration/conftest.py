"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and detector scores for
assertions. Scores come from Postgres via the in-process pipeline:
``calibration.runner`` runs the pipeline (if no sidecar exists) and
``_load_scores_for_strategy`` reads ``EntropyObjectRecord`` rows back
through ``measure_entropy()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from calibration import runner as runner_mod

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


def _strip_source_prefix(name: str) -> str:
    """Strip source_name__ prefix (e.g. detection_v1__invoices → invoices)."""
    if "__" in name:
        return name.split("__", 1)[1]
    return name


def _ensure_pipeline_run(strategy: str) -> runner_mod.CalibrationRun:
    """Return identifiers for the pipeline run; produce one if missing.

    Reads the sidecar at ``output/<strategy>/calibration_run.json`` if
    present; otherwise runs the pipeline and writes a fresh one. The
    sidecar lets pytest sessions reuse a previously-completed run when
    the underlying Postgres state is still intact.
    """
    sidecar = runner_mod.sidecar_path(strategy)
    if sidecar.exists():
        return runner_mod.CalibrationRun.from_json(sidecar.read_text())

    data_dir = DATA_DIR / strategy
    if not data_dir.exists():
        pytest.skip(
            f"No test data at {data_dir}. Run: "
            f"uv run python -m calibration.runner {strategy} --generate-only"
        )
    return runner_mod.run_pipeline(strategy)


def _load_scores_for_strategy(strategy: str) -> DetectorScores:
    """Read EntropyObjectRecord rows via measure_entropy() and adapt to DetectorScores."""
    run = _ensure_pipeline_run(strategy)

    runner_mod.bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.detectors.base import get_default_registry
    from dataraum.entropy.measurement import measure_entropy

    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        registry = get_default_registry()
        detector_ids = registry.get_detector_ids()
        # detector_id → dimension_path (and scope) directly from the registry
        path_by_detector = {d.detector_id: d.dimension_path for d in registry.get_all_detectors()}
        detector_by_path = {path: det_id for det_id, path in path_by_detector.items()}

        with workspace_mgr.session_scope() as session:
            measurement = measure_entropy(session, run.source_id, detector_ids)
    finally:
        workspace_mgr.close()

    result = DetectorScores()

    for dim_path, targets in measurement.column_details.items():
        detector_id = detector_by_path.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            ref = target.removeprefix("column:")
            parts = ref.split(".", 1)
            if len(parts) != 2:
                continue
            tbl, col = parts
            key = (_strip_source_prefix(tbl), col, detector_id)
            if key not in result.column or score > result.column[key]:
                result.column[key] = score

    for dim_path, targets in measurement.table_details.items():
        detector_id = detector_by_path.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            tbl = _strip_source_prefix(target.removeprefix("table:"))
            tbl_key = (tbl, detector_id)
            if tbl_key not in result.table or score > result.table[tbl_key]:
                result.table[tbl_key] = score

    for dim_path, targets in measurement.view_details.items():
        detector_id = detector_by_path.get(dim_path, dim_path.rsplit(".", 1)[-1])
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
def detector_scores(strategy_name: str) -> DetectorScores:
    """Detector scores for the current strategy, from Postgres via measure_entropy()."""
    return _load_scores_for_strategy(strategy_name)


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
# Clean baseline (always uses "clean" strategy data)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def clean_detector_scores() -> DetectorScores:
    """Detector scores for the clean baseline (no injections)."""
    return _load_scores_for_strategy("clean")


@pytest.fixture(scope="session")
def clean_pipeline_scores(
    clean_detector_scores: DetectorScores,
) -> dict[tuple[str, str, str], float]:
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
