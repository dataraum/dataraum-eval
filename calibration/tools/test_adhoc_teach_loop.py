"""_adhoc teach loop — entropy improvement through iterative teaching (DAT-251).

Tests the cold-start practitioner workflow: start with no vertical,
observe entropy, teach domain knowledge, re-measure, verify improvement.

This is the core UX test for _adhoc: the product works because the
teach → measure loop converges, not because config is pre-curated.

Requires: pipeline output from _adhoc vertical in output/detection-v1-adhoc/.
Run: uv run python -m calibration.runner detection-v1 --adhoc

Slow test — runs LLM calls for teach and re-measurement.
"""

from __future__ import annotations

import shutil
from collections.abc import Generator
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
# Fixtures — isolated _adhoc pipeline output
# ---------------------------------------------------------------------------

EVAL_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = EVAL_ROOT / "output"


@pytest.fixture(scope="module")
def adhoc_output_dir(strategy_output_dir: Path) -> Path:
    """Copy detection-v1 output to an isolated _adhoc directory.

    We start from the finance-vertical output (which has all phases complete)
    and test the teach loop on top of it. A full _adhoc pipeline run would
    be ideal but takes too long for CI.
    """
    adhoc_dir = OUTPUT_DIR / "detection-v1-adhoc-test"
    if adhoc_dir.exists():
        shutil.rmtree(adhoc_dir)
    shutil.copytree(strategy_output_dir, adhoc_dir)
    return adhoc_dir


@pytest.fixture(scope="module")
def adhoc_manager(adhoc_output_dir: Path) -> Generator[ConnectionManager]:
    config_root = adhoc_output_dir / "config"
    if config_root.exists():
        set_config_root(config_root)
    mgr = ConnectionManager(ConnectionConfig.for_directory(adhoc_output_dir))
    mgr.initialize()
    yield mgr
    mgr.close()


@pytest.fixture(scope="module")
def adhoc_source_id(adhoc_manager: ConnectionManager) -> str:
    with adhoc_manager.session_scope() as session:
        source = session.execute(select(Source)).scalars().first()
        assert source, "No source in _adhoc output"
        return source.source_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_score(
    manager: ConnectionManager,
    source_id: str,
    target: str,
    detector_id: str,
) -> float | None:
    """Get a single detector score for a target via measure_entropy."""
    registry = get_default_registry()
    detector_ids = [detector_id]

    with manager.session_scope() as session:
        measurement = measure_entropy(session, source_id, detector_ids)

    # Search column_details for the target
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
    """Apply a teach action and return the result."""
    if config_root is None:
        # Derive from manager's connection config (sqlite_path is in the output dir)
        config_root = manager.config.sqlite_path.parent / "config"
        if not config_root.is_dir():
            config_root = None

    with manager.session_scope() as session:
        # Resolve short table names in target
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
# Tests — teach → measure improvement cycles
# ---------------------------------------------------------------------------


class TestMetadataTeachImprovesMeasurement:
    """Metadata teaches (concept_property, relationship, explanation)
    apply immediately and should change scores on next measure."""

    def test_concept_property_reduces_business_meaning(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        """Teaching a business name on a garbage-named column should reduce
        business_meaning entropy (naming_clarity dimension)."""
        target_col = "invoices.rrflp_11_zp00"

        # Baseline score
        before = _get_score(
            adhoc_manager, adhoc_source_id,
            target_col, "business_meaning",
        )

        # Teach: give it a proper business name
        result = _teach(
            adhoc_manager, adhoc_source_id,
            teach_type="concept_property",
            target=target_col,
            params={"field_updates": {
                "business_name": "Vendor Identifier",
                "business_concept": "vendor_id",
                "semantic_role": "dimension",
            }},
        )
        assert result.get("status") == "applied", f"Teach failed: {result}"

        # Re-measure
        after = _get_score(
            adhoc_manager, adhoc_source_id,
            target_col, "business_meaning",
        )

        assert before is not None, "No baseline score for business_meaning"
        assert after is not None, "No post-teach score for business_meaning"
        assert after <= before, (
            f"business_meaning should not increase after teaching business_name: "
            f"before={before:.3f}, after={after:.3f}"
        )

    def test_explanation_persists_as_evidence(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        """Teaching an explanation should persist and appear in look."""
        target_col = "journal_lines.cost_center"
        result = _teach(
            adhoc_manager, adhoc_source_id,
            teach_type="explanation",
            target=target_col,
            params={
                "dimension": "value.nulls",
                "context": "Cost center is only assigned to expense journal lines. "
                "Null cost_center on revenue lines is expected business behavior.",
            },
        )
        assert result.get("status") == "applied", f"Teach failed: {result}"
        assert "teaching_id" in result


class TestSnippetReuseCycle:
    """SQL snippets saved by run_sql should be findable via search_snippets
    and reusable in subsequent queries."""

    def test_named_snippet_searchable(
        self,
        adhoc_manager: ConnectionManager,
    ) -> None:
        """A run_sql step with a named step_id becomes searchable."""
        with adhoc_manager.session_scope() as session:
            with adhoc_manager.duckdb_cursor() as cursor:
                # Run SQL with named step
                result = _run_sql(
                    session, cursor,
                    steps=[{
                        "step_id": "adhoc_revenue_test",
                        "sql": "SELECT SUM(credit) AS total FROM typed_detection_v1__journal_lines WHERE credit > 0",
                        "description": "Total credits for revenue test",
                    }],
                )
                assert "error" not in result, f"run_sql error: {result.get('error')}"
                assert result.get("snippet_summary", {}).get("saved", 0) >= 1

        # Search for it
        with adhoc_manager.session_scope() as session:
            search = _search_snippets(session, concepts=["adhoc_revenue_test"])
            assert "matches" in search, f"search_snippets returned no matches key: {search}"
            assert len(search["matches"]) >= 1, (
                f"Snippet 'adhoc_revenue_test' not found. "
                f"Vocabulary: {search.get('vocabulary', {})}"
            )

    def test_snippet_appears_in_look_when_concept_matches(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        """If a column has business_concept matching a snippet's standard_field,
        look should surface it as relevant_snippets."""
        # First teach a business_concept on a column
        _teach(
            adhoc_manager, adhoc_source_id,
            teach_type="concept_property",
            target="journal_lines.credit",
            params={"field_updates": {"business_concept": "adhoc_revenue_test"}},
        )

        # Now look at that column — should see the snippet
        with adhoc_manager.session_scope() as session:
            result = _look(session, target="journal_lines.credit")

        assert "relevant_snippets" in result, (
            f"Expected relevant_snippets in look result. "
            f"Keys: {list(result.keys())}"
        )
        snippets = result["relevant_snippets"]
        assert any("adhoc_revenue_test" in s.get("standard_field", "") for s in snippets), (
            f"Expected snippet with standard_field='adhoc_revenue_test'. "
            f"Got: {snippets}"
        )


@pytest.mark.slow
class TestConfigTeachWithRerun:
    """Config teaches write YAML and need a pipeline phase re-run.

    The teach → measure(target_phase) loop is the core _adhoc UX.
    These tests verify the full cycle works.

    Known issue: selective re-run doesn't work from any entry point:
    - calibration.runner.run_pipeline(target_phase=...) tries to re-register
      the source (UNIQUE constraint on sources.name)
    - MCP _run_pipeline(source_path=None, target_phase=...) fails because
      import phase can't find sources in multi-source mode

    Both xfails document the same root cause: RunConfig doesn't support
    "re-run phase X on existing pipeline output without re-importing."
    This is a blocking bug for the config teach → re-measure cycle.
    """

    @pytest.mark.xfail(
        reason="Selective phase re-run not supported: run_pipeline re-registers "
        "source (UNIQUE constraint), _run_pipeline(source_path=None) fails import. "
        "Handoff to context repo — RunConfig needs skip-import mode.",
        strict=True,
    )
    def test_validation_teach_and_rerun(
        self,
        strategy_output_dir: Path,
    ) -> None:
        """Teach a validation rule, re-run validation phase, verify it ran."""
        from calibration.runner import run_pipeline

        config_root = strategy_output_dir / "config"
        set_config_root(config_root)
        mgr = ConnectionManager(ConnectionConfig.for_directory(strategy_output_dir))
        mgr.initialize()

        try:
            with mgr.session_scope() as session:
                source = session.execute(select(Source)).scalars().first()
                assert source, "No source in pipeline output"
                source_id = source.source_id

            # Teach a new validation rule
            result = _teach(
                mgr, source_id,
                teach_type="validation",
                params={
                    "validation_id": "test_positive_amounts",
                    "name": "Invoice amounts must be positive",
                    "description": "All invoice amounts should be greater than zero",
                    "check_type": "constraint",
                    "sql_hints": "SELECT * FROM typed_detection_v1__invoices WHERE amount <= 0",
                    "expected_outcome": "No rows returned means all amounts are positive",
                },
            )
            assert result.get("status") == "applied", f"Teach failed: {result}"
            assert "measurement_hint" in result

            # Re-run validation phase — this is what measure(target_phase=...) does
            run_result = run_pipeline("detection-v1", target_phase="validation")
            assert run_result.success, "Pipeline re-run failed"
        finally:
            mgr.close()


class TestMeasureTrajectory:
    """Verify that score trajectory can be tracked across teach cycles."""

    def test_trajectory_records_improvement(
        self,
        adhoc_manager: ConnectionManager,
        adhoc_source_id: str,
    ) -> None:
        """Multiple teaches on the same column should show monotonic improvement
        (or at least no regression) in the targeted dimension."""
        trajectory = ScoreTrajectory()
        target = "invoices.xq_v7kl"  # garbage name for payment_terms

        # Baseline
        with adhoc_manager.session_scope() as session:
            baseline = _measure(session, target=target)
        assert baseline.get("status") == "complete" or "points" in baseline
        trajectory.record("baseline", baseline.get("points", []))

        # Teach concept_property
        _teach(
            adhoc_manager, adhoc_source_id,
            teach_type="concept_property",
            target=target,
            params={"field_updates": {
                "business_name": "Payment Terms",
                "business_concept": "payment_terms",
                "semantic_role": "dimension",
            }},
        )

        # Post-teach measure
        with adhoc_manager.session_scope() as session:
            post_teach = _measure(session, target=target)
        trajectory.record("after_teach", post_teach.get("points", []))

        # Find the business_meaning dimension point
        bm_target = None
        for p in baseline.get("points", []):
            if "naming_clarity" in p["dimension"]:
                bm_target = p["target"]
                break

        if bm_target:
            delta = trajectory.delta(
                bm_target,
                "semantic.business_meaning.naming_clarity",
                "baseline", "after_teach",
            )
            # Score should not increase (improvement = decrease or stable)
            assert delta is not None, "Could not compute delta"
            assert delta <= 0.05, (
                f"business_meaning regressed after teach: delta={delta:.3f}"
            )
