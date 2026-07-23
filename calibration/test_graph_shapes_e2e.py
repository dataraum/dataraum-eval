"""Graph structural-shape oracles — every bound og_* element instantiates in a MATCH.

The Q2 ruling (docs/oracle_backlog_graph_close.md §Answers): the MATCH-shape
inventory is a GROWTH surface (12 vertex / 15 edge kinds and rising through band
6), so it lives in its own module whose ``version`` tracks the graph schema —
separate from ``test_grounding_e2e.py``, whose version tracks semantic-judgment
grading. The shapes moved here from that module (its v1→v2 bump); their prior
nodeids show as ``gone`` in the verdict store — intended, moved.

The contract per element (unchanged from the P2 originals): view absent → skip
(pre-cutover engine); view present but empty on a Tier-A corpus → FAIL (absence
falls loud); rows present but the MATCH returns none → FAIL (dangling keys or a
label/binding mismatch — the defect the every-bound-edge-ships-a-MATCH invariant
exists to catch). Conditioned-hard entries (O4: validity scope) skip with the
``conditional-cell:`` reason prefix when their runtime condition does not hold —
the Q5 idiom; whether the condition SHOULD hold is the cycles oracle's job.

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``; pytest auto-collects.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import is_wild, read_view_exists
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")

# Every bound og_* element and the MATCH it must instantiate in. The capability
# probe is the element VIEW's existence; the assertion is the graph BINDING (a
# view can hold rows whose keys dangle — only a MATCH proves the edge).
_MATCH_SHAPES: dict[str, str] = {
    # --- P2 grounding reification (moved from test_grounding_e2e v1) ---------
    "og_grounding": (
        "SELECT count(*) FROM GRAPH_TABLE ({graph} MATCH (g IS grounding_node) COLUMNS (1 AS one))"
    ),
    "og_grounded_by": (
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (c IS concept_node)-[e IS grounded_by]->(g IS grounding_node) "
        "COLUMNS (1 AS one))"
    ),
    "og_uses": (
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (g IS grounding_node)-[u IS uses]->(col IS column_node) "
        "COLUMNS (1 AS one))"
    ),
    # --- O3 (P7/DAT-732) metric DAG — seeded from the vertical, so present on
    # --- every declaring corpus (finance seeds working-capital metrics) --------
    "og_metrics": (
        "SELECT count(*) FROM GRAPH_TABLE ({graph} MATCH (m IS metric_node) COLUMNS (1 AS one))"
    ),
    "og_derives_from": (
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (m IS metric_node)-[d IS derives_from]->(c IS concept_node) "
        "COLUMNS (1 AS one))"
    ),
    "og_has_parameter": (
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (m IS metric_node)-[p IS has_parameter]->(par IS parameter_node) "
        "COLUMNS (1 AS one))"
    ),
}

# CONDITIONED-HARD shapes (the Q5 idiom): hard-asserted only when their runtime
# condition holds in THIS run's materialized cell; otherwise skip with the
# `conditional-cell:` reason prefix so sweep accounting can partition designed
# conditioning from silent stand-downs. The condition's own recall belongs to
# another oracle (cycles recall for the status cycle; the DAT-787 member-precision
# oracle for filter declarations) — these entries grade PLUMBING only.
#
# * O4 (P8/DAT-733, owner-ruled): og_validity_filter / og_scoped_by exist iff a
#   MEASURED status cycle was detected (status_column/completion_value/
#   completion_rate all non-NULL in detected_business_cycles).
# * DAT-787: og_dim_members / og_filtered_by exist iff >= 1 healthy grounding
#   declared typed filter_members in its provenance (prompt v10.0 — an
#   LLM-selective declaration; zero declarations is a legitimate run, not a
#   binding defect).
_CONDITIONED_SHAPES: dict[str, tuple[str, str]] = {
    "og_validity_filter": (
        "status_cycle",
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (v IS validity_filter) COLUMNS (1 AS one))",
    ),
    "og_scoped_by": (
        "status_cycle",
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (t IS table_node)-[s IS scoped_by]->(v IS validity_filter) "
        "COLUMNS (1 AS one))",
    ),
    "og_dim_members": (
        "filter_members",
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (dm IS dim_member) COLUMNS (1 AS one))",
    ),
    "og_filtered_by": (
        "filter_members",
        "SELECT count(*) FROM GRAPH_TABLE ({graph} "
        "MATCH (g IS grounding_node)-[f IS filtered_by]->(dm IS dim_member) "
        "COLUMNS (1 AS one))",
    ),
}


def _condition_holds(session: Any, condition: str, read_schema: str) -> tuple[bool, str]:
    """Evaluate a conditioned shape's runtime condition on the materialized cell."""
    from sqlalchemy import text

    if condition == "status_cycle":
        n = session.execute(
            text(
                "SELECT count(*) FROM "
                f'"{read_schema}".current_detected_business_cycles '
                "WHERE status_column IS NOT NULL AND completion_value IS NOT NULL "
                "AND completion_rate IS NOT NULL"
            )
        ).scalar()
        return bool(n), "no MEASURED status cycle detected in this run"
    if condition == "filter_members":
        n = session.execute(
            text(
                "SELECT count(*) FROM "
                f'"{read_schema}".current_groundings '
                "WHERE NOT failed AND provenance::text LIKE '%filter_members%'"
            )
        ).scalar()
        return bool(n), "no healthy grounding declared filter_members this run"
    raise ValueError(f"unknown condition {condition!r}")


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    """Skip without a completed run; otherwise activate the strategy's workspace."""
    require_pipeline_run(strategy_name)


def _read_schema(session: Any) -> str:
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    return read_schema_name_for(str(session.execute(text("SELECT current_schema()")).scalar()))


def _assert_shape(element: str, shape: str, metadata_truth: dict[str, Any]) -> None:
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, element):
            pytest.skip(f"{element} element view absent — pre-cutover engine")
        read_schema = _read_schema(session)
        direct = session.execute(
            text(f'SELECT count(*) FROM "{read_schema}".{element}')  # noqa: S608 (fixed names)
        ).scalar()
        # The defect this catches is a DANGLING BINDING — rows present, MATCH empty.
        # A Tier-B corpus declares no concepts, so an empty substrate there is the
        # corpus, not a defect; Tier A keeps falling loud.
        if not direct and is_wild(metadata_truth):
            pytest.skip(f"{element} empty on a Tier-B corpus — nothing declared to project")
        assert direct, (
            f"{element} exists but has ZERO rows on the finance corpus — an empty "
            "graph substrate is a stop-condition (absence falls loud), never a green run"
        )
        graph = f'"{read_schema}".operating_model'
        matched = session.execute(text(shape.format(graph=graph))).scalar()

    print(f"\n[match shape] {element}: {direct} view rows, {matched} MATCH rows")
    assert matched, (
        f"{element} holds {direct} rows but its MATCH returns none — the element never "
        "instantiates in the property graph (dangling keys or a label/binding mismatch)"
    )


@pytest.mark.llm
@pytest.mark.parametrize("element", sorted(_MATCH_SHAPES))
def test_element_instantiates_in_match(
    element: str, strategy_name: str, metadata_truth: dict[str, Any]
) -> None:
    """A present og_* element view has rows AND those rows instantiate in a PGQ MATCH."""
    _assert_shape(element, _MATCH_SHAPES[element], metadata_truth)


@pytest.mark.llm
@pytest.mark.parametrize("element", sorted(_CONDITIONED_SHAPES))
def test_conditioned_element_instantiates_in_match(
    element: str, strategy_name: str, metadata_truth: dict[str, Any]
) -> None:
    """A conditioned og_* element instantiates in a MATCH WHEN its condition holds.

    Condition unmet → `conditional-cell:` skip (designed stand-down, partitionable
    in the verdict store); condition met → the full hard contract (rows + MATCH).
    """
    condition, shape = _CONDITIONED_SHAPES[element]
    with workspace_session() as session:
        if not read_view_exists(session, element):
            pytest.skip(f"{element} element view absent — pre-cutover engine")
        holds, why = _condition_holds(session, condition, _read_schema(session))
    if not holds:
        pytest.skip(f"conditional-cell: {why} ({element} conditioned-hard, Q5 idiom)")
    _assert_shape(element, shape, metadata_truth)
