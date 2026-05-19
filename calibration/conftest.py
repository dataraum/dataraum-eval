"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and detector scores for assertions.
Scores come from the dataraum control plane over HTTP MCP — the compose stack
is auto-started by the ``mcp_stack`` fixture. Strategy is configurable via
``--strategy`` (default: ``detection-v1``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from calibration import runner as runner_mod
from calibration.mcp_client import mcp_session
from calibration.stack import StackHandle, up

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
    """Strip source_name__ prefix from table names (e.g. detection_v1__invoices → invoices)."""
    if "__" in name:
        return name.split("__", 1)[1]
    return name


def _points_to_scores(points: list[dict[str, Any]]) -> DetectorScores:
    """Translate the ``points`` array from measure() into DetectorScores.

    Each point: ``{"target": "column:tbl.col"|"table:tbl"|"view:vw",
    "dimension": "layer.dim.sub_dim", "detector_id": str, "score": float}``.
    """
    result = DetectorScores()
    for pt in points:
        target = pt["target"]
        score = float(pt["score"])
        detector_id = str(pt.get("detector_id") or str(pt["dimension"]).rsplit(".", 1)[-1])

        if target.startswith("column:"):
            ref = target.removeprefix("column:")
            parts = ref.split(".", 1)
            if len(parts) != 2:
                continue
            tbl, col = parts
            key = (_strip_source_prefix(tbl), col, detector_id)
            if key not in result.column or score > result.column[key]:
                result.column[key] = score
        elif target.startswith("table:"):
            tbl = _strip_source_prefix(target.removeprefix("table:"))
            tbl_key = (tbl, detector_id)
            if tbl_key not in result.table or score > result.table[tbl_key]:
                result.table[tbl_key] = score
        elif target.startswith("view:"):
            vw = target.removeprefix("view:")
            vw_key = (vw, detector_id)
            if vw_key not in result.view or score > result.view[vw_key]:
                result.view[vw_key] = score
    return result


async def _measure_for_strategy(handle: StackHandle, strategy: str) -> DetectorScores:
    """Open an MCP session, ensure the strategy's pipeline has run, return scores."""
    async with mcp_session(handle) as s:
        await runner_mod.setup_strategy(s, strategy)
        final = await runner_mod._wait_for_pipeline(s)
        return _points_to_scores(final.get("points", []))


def _load_scores_for_strategy(strategy: str) -> DetectorScores:
    """Drive the control plane to produce scores for ``strategy``.

    Generates data if missing, brings up the compose stack, runs the pipeline
    via MCP, and aggregates the measure() ``points`` into DetectorScores.
    """
    data_dir = DATA_DIR / strategy
    if not data_dir.exists():
        pytest.skip(
            f"No test data at {data_dir}. Run: "
            f"uv run python -m calibration.runner {strategy} --generate-only"
        )
    handle = up()
    return asyncio.run(_measure_for_strategy(handle, strategy))


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
def mcp_stack() -> StackHandle:
    """Ensure the dataraum control-plane compose stack is up; return the MCP handle."""
    return up()


@pytest.fixture
async def mcp_client(mcp_stack: StackHandle) -> AsyncIterator[Any]:
    """Function-scoped MCP ClientSession.

    A session-scoped client triggers ``McpError: Session terminated`` after
    the first test — the streamable-HTTP session is bound to its creating
    event loop and pytest-asyncio's per-test loop closes between tests. A
    fresh client per test is correct; the underlying pipeline state lives
    server-side in Postgres and is reused across clients.
    """
    async with mcp_session(mcp_stack) as session:
        yield session


@pytest.fixture(scope="session")
def detector_scores(strategy_name: str, mcp_stack: StackHandle) -> DetectorScores:
    """Detector scores for the current strategy, sourced via HTTP MCP measure()."""
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
def clean_detector_scores(mcp_stack: StackHandle) -> DetectorScores:
    """Detector scores for the clean baseline (no injections)."""
    return _load_scores_for_strategy("clean")


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
