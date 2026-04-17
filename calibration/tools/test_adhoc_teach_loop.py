"""_adhoc teach loop — entropy improvement through iterative teaching (DAT-251).

Tests the cold-start practitioner workflow: start with no vertical,
observe entropy, teach domain knowledge, re-measure, verify improvement.

This is the core UX test for _adhoc: the product works because the
teach → measure loop converges, not because config is pre-curated.

Two test modes:
- Direct handler tests (fast): metadata teaches that apply instantly
- MCP client tests (slow): config teaches that need pipeline re-run
  via measure(target_phase=...). Uses in-memory MCP client to test
  the full call_tool dispatch including state management.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from dataraum.core.config import set_config_root
from dataraum.core.connections import ConnectionConfig, ConnectionManager
from dataraum.entropy.detectors.base import get_default_registry
from dataraum.entropy.measurement import measure_entropy
from dataraum.mcp.server import _look, _measure, _run_sql, _search_snippets
from dataraum.mcp.teach import handle_teach
from dataraum.storage import Source
from mcp.client.session import ClientSession
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Score tracking
# ---------------------------------------------------------------------------


@dataclass
class ScoreSnapshot:
    """A point-in-time entropy score for a (target, dimension) pair."""

    target: str
    dimension: str
    score: float
    step: str  # what happened before this snapshot


@dataclass
class ScoreTrajectory:
    """Tracks score changes across teach → measure cycles."""

    snapshots: list[ScoreSnapshot] = field(default_factory=list)

    def record(self, step: str, points: list[dict[str, Any]]) -> None:
        for p in points:
            self.snapshots.append(
                ScoreSnapshot(
                    target=p["target"],
                    dimension=p["dimension"],
                    score=p["score"],
                    step=step,
                )
            )

    def score_at(self, target: str, dimension: str, step: str) -> float | None:
        for s in reversed(self.snapshots):
            if s.target == target and s.dimension == dimension and s.step == step:
                return s.score
        return None

    def delta(self, target: str, dimension: str, before: str, after: str) -> float | None:
        s_before = self.score_at(target, dimension, before)
        s_after = self.score_at(target, dimension, after)
        if s_before is not None and s_after is not None:
            return s_after - s_before
        return None


# ---------------------------------------------------------------------------
# Fixtures — isolated pipeline output for direct handler tests
# ---------------------------------------------------------------------------

EVAL_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = EVAL_ROOT / "output"


@pytest.fixture(scope="module")
def adhoc_output_dir(strategy_output_dir: Path) -> Path:
    """Copy detection-v1 output to an isolated directory."""
    adhoc_dir = OUTPUT_DIR / "detection-v1-adhoc-test"
    if adhoc_dir.exists():
        shutil.rmtree(adhoc_dir)
    shutil.copytree(strategy_output_dir, adhoc_dir)
    return adhoc_dir


@pytest.fixture(scope="module")
def adhoc_manager(adhoc_output_dir: Path) -> Generator[ConnectionManager]:
    from dataraum.core.config import reset_config_root

    config_root = adhoc_output_dir / "config"
    if config_root.exists():
        set_config_root(config_root)
    mgr = ConnectionManager(ConnectionConfig.for_directory(adhoc_output_dir))
    mgr.initialize()
    yield mgr
    mgr.close()
    reset_config_root()


@pytest.fixture(scope="module")
def adhoc_source_id(adhoc_manager: ConnectionManager) -> str:
    with adhoc_manager.session_scope() as session:
        source = session.execute(select(Source)).scalars().first()
        assert source, "No source in _adhoc output"
        return source.source_id


# ---------------------------------------------------------------------------
# Fixtures — MCP client for full call_tool dispatch
# ---------------------------------------------------------------------------


async def _call(client: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and parse the JSON response."""
    result = await client.call_tool(name, arguments)
    for content in result.content:
        if hasattr(content, "text"):
            parsed: dict[str, Any] = json.loads(content.text)
            return parsed
    return {"error": "No text content in response"}


@pytest.fixture(scope="module")
async def mcp_session(
    adhoc_output_dir: Path,
) -> AsyncGenerator[ClientSession]:
    """MCP client with an active session on the isolated output.

    Handles the full lifecycle: create server → begin session → yield → end session.
    The server uses the copied pipeline output, so teaches don't pollute
    the real detection-v1 output.
    """
    from dataraum.mcp.server import create_server
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(output_dir=adhoc_output_dir)

    async with create_connected_server_and_client_session(server) as client:
        # Begin session — sources are already registered in the copied DB
        begin = await _call(client, "begin_session", {
            "intent": "teach loop test",
            "contract": "aggregation_safe",
            "vertical": "finance",
        })
        assert "error" not in begin, f"begin_session failed: {begin}"

        yield client

        # End session
        await _call(client, "end_session", {"outcome": "delivered"})


# ---------------------------------------------------------------------------
# Direct handler helpers (for metadata teaches that don't need re-run)
# ---------------------------------------------------------------------------


def _get_score(
    manager: ConnectionManager,
    source_id: str,
    target: str,
    detector_id: str,
) -> float | None:
    """Get a single detector score for a target via measure_entropy."""
    registry = get_default_registry()

    with manager.session_scope() as session:
        measurement = measure_entropy(session, source_id, [detector_id])

    for dim_path, targets in measurement.column_details.items():
        for det in registry.get_all_detectors():
            if det.detector_id == detector_id and det.dimension_path == dim_path:
                for tgt, score in targets.items():
                    if target in tgt:
                        return score
    return None


def _teach(
    manager: ConnectionManager,
    source_id: str,
    teach_type: str,
    params: dict[str, Any],
    target: str | None = None,
    vertical: str = "finance",
    config_root: Path | None = None,
) -> dict[str, Any]:
    """Apply a teach action via direct handler call."""
    if config_root is None:
        config_root = manager.config.sqlite_path.parent / "config"
        if not config_root.is_dir():
            config_root = None

    with manager.session_scope() as session:
        if target and "." in target:
            from dataraum.mcp.server import _resolve_teach_target

            target = _resolve_teach_target(session, source_id, target)

        result = handle_teach(
            teach_type=teach_type,
            params=params,
            source_id=source_id,
            session=session,
            vertical=vertical,
            config_root=config_root,
            target=target,
        )
    return result


# ---------------------------------------------------------------------------
# Tests — metadata teaches (direct handler, fast)
# ---------------------------------------------------------------------------


class TestMetadataTeachImprovesMeasurement:
    """Metadata teaches apply immediately and should change scores on next measure."""

    def test_concept_property_reduces_business_meaning(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        target_col = "invoices.rrflp_11_zp00"

        before = _get_score(adhoc_manager, adhoc_source_id, target_col, "business_meaning")

        result = _teach(
            adhoc_manager,
            adhoc_source_id,
            teach_type="concept_property",
            target=target_col,
            params={
                "field_updates": {
                    "business_name": "Vendor Identifier",
                    "business_concept": "vendor_id",
                    "semantic_role": "dimension",
                }
            },
        )
        assert result.get("status") == "applied", f"Teach failed: {result}"

        after = _get_score(adhoc_manager, adhoc_source_id, target_col, "business_meaning")

        assert before is not None, "No baseline score for business_meaning"
        assert after is not None, "No post-teach score for business_meaning"
        assert after <= before, (
            f"business_meaning should not increase after teaching: "
            f"before={before:.3f}, after={after:.3f}"
        )

    def test_explanation_persists(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        result = _teach(
            adhoc_manager,
            adhoc_source_id,
            teach_type="explanation",
            target="journal_lines.cost_center",
            params={
                "dimension": "value.nulls",
                "context": "Cost center is only assigned to expense journal lines. "
                "Null cost_center on revenue lines is expected business behavior.",
            },
        )
        assert result.get("status") == "applied", f"Teach failed: {result}"
        assert "teaching_id" in result


# ---------------------------------------------------------------------------
# Tests — snippet cycle (direct handler, fast)
# ---------------------------------------------------------------------------


class TestSnippetReuseCycle:
    def test_named_snippet_searchable(self, adhoc_manager: ConnectionManager) -> None:
        with adhoc_manager.session_scope() as session:
            with adhoc_manager.duckdb_cursor() as cursor:
                result = _run_sql(
                    session,
                    cursor,
                    steps=[
                        {
                            "step_id": "adhoc_revenue_test",
                            "sql": "SELECT SUM(credit) AS total "
                            "FROM typed_detection_v1__journal_lines WHERE credit > 0",
                            "description": "Total credits for revenue test",
                        }
                    ],
                )
                assert "error" not in result, f"run_sql error: {result.get('error')}"
                assert result.get("snippet_summary", {}).get("saved", 0) >= 1

        with adhoc_manager.session_scope() as session:
            search = _search_snippets(session, concepts=["adhoc_revenue_test"])
            assert "matches" in search
            assert len(search["matches"]) >= 1

    def test_snippet_appears_in_look_when_concept_matches(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        _teach(
            adhoc_manager,
            adhoc_source_id,
            teach_type="concept_property",
            target="journal_lines.credit",
            params={"field_updates": {"business_concept": "adhoc_revenue_test"}},
        )

        with adhoc_manager.session_scope() as session:
            result = _look(session, target="journal_lines.credit")

        assert "relevant_snippets" in result
        snippets = result["relevant_snippets"]
        assert any("adhoc_revenue_test" in s.get("standard_field", "") for s in snippets)


# ---------------------------------------------------------------------------
# Tests — config teach with re-run via MCP client (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestConfigTeachWithRerunMCP:
    """Config teaches via the full MCP call_tool dispatch.

    Uses the in-memory MCP client so teach → measure(target_phase)
    goes through the real server state management and pipeline trigger.
    """

    @pytest.mark.anyio
    async def test_validation_teach_and_remeasure(
        self,
        mcp_session: ClientSession,
    ) -> None:
        """Teach a validation rule via MCP, then call measure(target_phase)."""
        # Teach a validation rule
        teach_result = await _call(
            mcp_session,
            "teach",
            {
                "type": "validation",
                "params": {
                    "validation_id": "test_positive_amounts",
                    "name": "Invoice amounts must be positive",
                    "description": "All invoice amounts should be greater than zero",
                    "check_type": "constraint",
                    "sql_hints": (
                        "SELECT * FROM typed_detection_v1__invoices WHERE amount <= 0"
                    ),
                    "expected_outcome": "No rows returned means all amounts are positive",
                },
            },
        )
        assert teach_result.get("status") == "applied", f"Teach failed: {teach_result}"
        assert "measurement_hint" in teach_result

        # Re-measure with target_phase — this triggers pipeline re-run
        measure_result = await _call(
            mcp_session,
            "measure",
            {"target_phase": "validation"},
        )

        # The response should either be "complete" (re-run succeeded)
        # or "pipeline_triggered" (fire-and-forget mode)
        status = measure_result.get("status")
        assert status in ("complete", "pipeline_triggered", "running"), (
            f"Unexpected measure status after target_phase re-run: {status}. "
            f"Result: {measure_result}"
        )

    @pytest.mark.anyio
    async def test_concept_teach_and_remeasure(
        self,
        mcp_session: ClientSession,
    ) -> None:
        """Teach a concept via MCP, then call measure(target_phase='semantic')."""
        teach_result = await _call(
            mcp_session,
            "teach",
            {
                "type": "concept",
                "params": {
                    "name": "test_operating_expenses",
                    "indicators": ["expense", "cost", "opex"],
                    "description": "Operating expenses for test",
                },
            },
        )
        assert teach_result.get("status") == "applied", f"Teach failed: {teach_result}"
        assert "measurement_hint" in teach_result
        assert "semantic" in teach_result["measurement_hint"]

        # Re-measure with target_phase
        measure_result = await _call(
            mcp_session,
            "measure",
            {"target_phase": "semantic"},
        )

        status = measure_result.get("status")
        assert status in ("complete", "pipeline_triggered", "running"), (
            f"Unexpected measure status: {status}. Result: {measure_result}"
        )


# ---------------------------------------------------------------------------
# Tests — trajectory tracking (direct handler, fast)
# ---------------------------------------------------------------------------


class TestMeasureTrajectory:
    def test_trajectory_records_improvement(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        trajectory = ScoreTrajectory()
        target = "invoices.xq_v7kl"

        with adhoc_manager.session_scope() as session:
            baseline = _measure(session, target=target)
        assert baseline.get("status") == "complete" or "points" in baseline
        trajectory.record("baseline", baseline.get("points", []))

        _teach(
            adhoc_manager,
            adhoc_source_id,
            teach_type="concept_property",
            target=target,
            params={
                "field_updates": {
                    "business_name": "Payment Terms",
                    "business_concept": "payment_terms",
                    "semantic_role": "dimension",
                }
            },
        )

        with adhoc_manager.session_scope() as session:
            post_teach = _measure(session, target=target)
        trajectory.record("after_teach", post_teach.get("points", []))

        bm_target = None
        for p in baseline.get("points", []):
            if "naming_clarity" in p["dimension"]:
                bm_target = p["target"]
                break

        if bm_target:
            delta = trajectory.delta(
                bm_target,
                "semantic.business_meaning.naming_clarity",
                "baseline",
                "after_teach",
            )
            assert delta is not None, "Could not compute delta"
            assert delta <= 0.05, (
                f"business_meaning regressed after teach: delta={delta:.3f}"
            )
