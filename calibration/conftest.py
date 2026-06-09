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
    """Detector scores from persisted EntropyObjectRecord rows, split by scope."""

    # Column-scoped: (table, column, detector_id) → score
    column: dict[tuple[str, str, str], float] = field(default_factory=dict)
    # Table-scoped: (table, detector_id) → score
    table: dict[tuple[str, str], float] = field(default_factory=dict)
    # View-scoped: (view_name, detector_id) → score
    view: dict[tuple[str, str], float] = field(default_factory=dict)
    # Relationship-scoped (DAT-408): a relationship object is keyed
    # ``relationship:{from_col_id}::{to_col_id}``. We index its score under BOTH
    # endpoint columns as (table, column, detector_id), so an injection that names
    # one FK column (e.g. payments.invoice_id) finds the relationship's score.
    relationship: dict[tuple[str, str, str], float] = field(default_factory=dict)


def _strip_source_prefix(name: str) -> str:
    """Strip source_name__ prefix (e.g. src_<digest>__invoices → invoices)."""
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


def _head_resolved_entropy_rows(session: Any, session_id: str) -> list[Any]:
    """Promoted-run ``entropy_objects`` for a session — head-resolved (DAT-447 Step 0).

    Rows from multiple runs coexist in one session: add_source seals a table-head,
    begin_session a session-head, and a teach RE-RUN promotes a fresh head while the
    prior run's rows remain in the table. Reading raw ``entropy_objects`` by
    ``session_id`` and taking ``max()`` would surface a stale pre-teach score and HIDE
    a post-teach DROP. The ``current_entropy_objects`` view returns only rows whose run
    is the promoted head, so a re-run's score replaces — does not max-with — the prior
    run's. (No-op while there is one promoted run; load-bearing once teach re-runs land.)
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(session.execute(text("SELECT current_schema()")).scalar())
    rows: list[Any] = session.execute(
        text(f'SELECT * FROM "{read_schema}".current_entropy_objects WHERE session_id = :sid'),
        {"sid": session_id},
    ).all()
    return rows


def _load_scores_for_strategy(strategy: str) -> DetectorScores:
    """Read promoted-run entropy objects and aggregate into DetectorScores.

    Post-DAT-399/408: ``entropy/measurement.py`` (``measure_entropy``) is gone and
    ``entropy_objects`` no longer carries ``source_id``. Scores are read off the
    HEAD-RESOLVED view (see ``_head_resolved_entropy_rows``), bucketed by ``target``
    prefix (``column:`` / ``table:`` / ``view:`` / ``relationship:``). For each
    (target, detector) the max score is kept.
    """
    run = _ensure_pipeline_run(strategy)

    runner_mod.bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.models import parse_relationship_target
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as session:
            records = _head_resolved_entropy_rows(session, run.session_id)
            # column_id → (table_name, column_name): relationship rows carry no
            # table_id/column_id — identity is the two column ids inside ``target``.
            table_names = {t.table_id: t.table_name for t in session.execute(select(Table)).scalars()}
            col_names = {
                c.column_id: (table_names.get(c.table_id, ""), c.column_name)
                for c in session.execute(select(Column)).scalars()
            }
    finally:
        workspace_mgr.close()

    result = DetectorScores()

    def _keep_max(d: dict[Any, float], key: Any, score: float) -> None:
        if key not in d or score > d[key]:
            d[key] = score

    for rec in records:
        det, target, score = rec.detector_id, rec.target, rec.score
        if target.startswith("column:"):
            parts = target.removeprefix("column:").split(".", 1)
            if len(parts) != 2:
                continue
            tbl, col = parts
            _keep_max(result.column, (_strip_source_prefix(tbl), col, det), score)
        elif target.startswith("table:"):
            _keep_max(result.table, (_strip_source_prefix(target.removeprefix("table:")), det), score)
        elif target.startswith("view:"):
            _keep_max(result.view, (target.removeprefix("view:"), det), score)
        else:
            pair = parse_relationship_target(target)
            if pair is None:
                continue
            # Index the relationship's score under BOTH endpoint columns, so an
            # injection naming either FK side (table, col, detector) resolves it.
            for col_id in pair:
                tbl, col = col_names.get(col_id, ("", ""))
                if tbl and col:
                    _keep_max(result.relationship, (_strip_source_prefix(tbl), col, det), score)

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


@pytest.fixture(scope="session")
def pipeline_relationship_scores(
    detector_scores: DetectorScores,
) -> dict[tuple[str, str, str], float]:
    """Relationship-scoped scores, indexed per endpoint: (table, column, detector_id) → score."""
    return detector_scores.relationship


# ---------------------------------------------------------------------------
# Clean baseline (always uses "clean" strategy data)
# ---------------------------------------------------------------------------


def _assemble_readiness(
    strategy: str,
) -> tuple[Any, dict[str, tuple[str, str]]]:
    """Assemble the readiness context for a strategy's persisted records.

    Returns ``(ctx, col_names)`` where ``ctx.columns`` is keyed by target string
    (``column:`` AND ``relationship:`` targets, DAT-408) and ``col_names`` maps
    ``column_id → (table_name, column_name)`` for resolving relationship
    endpoints.
    """
    run = _ensure_pipeline_run(strategy)
    runner_mod.bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.models import EntropyObject
    from dataraum.entropy.views.readiness_context import assemble_readiness_context
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as session:
            records = _head_resolved_entropy_rows(session, run.session_id)
            # Reconstruct domain objects for the rollup (DAT-399: read-path swap from
            # the retired measurement module to the readiness-context assembler).
            # Head-resolved (DAT-447 Step 0) so a teach re-run's drop is visible.
            objects = [
                EntropyObject(
                    object_id=r.object_id,
                    layer=r.layer,
                    dimension=r.dimension,
                    sub_dimension=r.sub_dimension,
                    target=r.target,
                    score=r.score,
                    evidence=r.evidence if isinstance(r.evidence, list) else [],
                    detector_id=r.detector_id,
                )
                for r in records
            ]
            ctx = assemble_readiness_context(objects)
            table_names = {t.table_id: t.table_name for t in session.execute(select(Table)).scalars()}
            col_names = {
                c.column_id: (table_names.get(c.table_id, ""), c.column_name)
                for c in session.execute(select(Column)).scalars()
            }
    finally:
        workspace_mgr.close()
    return ctx, col_names


def _load_intent_readiness(strategy: str) -> dict[tuple[str, str], dict[str, str]]:
    """Per-column intent readiness from the loss rollup.

    Loads persisted ``EntropyObjectRecord`` rows for the source, assembles the
    readiness context (loss table: risk = clamp01(Σ weight·value), banded), and maps
    each column target to ``{intent_name: readiness}``. Implementation-agnostic:
    validates the readiness *output*, not the rollup engine (DAT-442).
    """
    ctx, _ = _assemble_readiness(strategy)

    result: dict[tuple[str, str], dict[str, str]] = {}
    for target, col in ctx.columns.items():
        ref = target.removeprefix("column:")
        parts = ref.split(".", 1)
        if len(parts) != 2:
            continue
        tbl, column = parts
        result[(_strip_source_prefix(tbl), column)] = {
            intent.intent_name: intent.readiness for intent in col.intents
        }
    return result


_READINESS_RANK = {"ready": 0, "investigate": 1, "blocked": 2}


def _load_relationship_readiness(strategy: str) -> dict[tuple[str, str], dict[str, str]]:
    """Relationship-grain intent readiness, indexed per endpoint column.

    Relationship problems live at relationship grain (DAT-408/DAT-405 decision):
    the assembler rolls ``relationship:{from_col_id}::{to_col_id}`` targets
    through the same loss rollup, and this maps each one onto BOTH endpoint
    ``(table, column)`` keys so an expectation naming the FK column resolves it.
    An endpoint in several relationships keeps the WORST readiness per intent —
    the band a practitioner should see for that join.
    """
    from dataraum.entropy.models import parse_relationship_target

    ctx, col_names = _assemble_readiness(strategy)

    result: dict[tuple[str, str], dict[str, str]] = {}
    for target, col in ctx.columns.items():
        if not target.startswith("relationship:"):
            continue
        pair = parse_relationship_target(target)
        if pair is None:
            continue
        intents = {intent.intent_name: intent.readiness for intent in col.intents}
        for col_id in pair:
            tbl, column = col_names.get(col_id, ("", ""))
            if not (tbl and column):
                continue
            key = (_strip_source_prefix(tbl), column)
            existing = result.setdefault(key, {})
            for intent_name, readiness in intents.items():
                prev = existing.get(intent_name)
                if prev is None or _READINESS_RANK[readiness] > _READINESS_RANK[prev]:
                    existing[intent_name] = readiness
    return result


@pytest.fixture(scope="session")
def intent_readiness(strategy_name: str) -> dict[tuple[str, str], dict[str, str]]:
    """(table, column) → {intent_name: readiness} for the current strategy."""
    return _load_intent_readiness(strategy_name)


@pytest.fixture(scope="session")
def relationship_intent_readiness(
    strategy_name: str,
) -> dict[tuple[str, str], dict[str, str]]:
    """Relationship-grain readiness indexed per endpoint (table, column)."""
    return _load_relationship_readiness(strategy_name)


@pytest.fixture(scope="session")
def clean_intent_readiness() -> dict[tuple[str, str], dict[str, str]]:
    """(table, column) → {intent_name: readiness} for the clean baseline."""
    return _load_intent_readiness("clean")


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
