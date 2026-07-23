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
}

# O4 (P8/DAT-733) validity-scope shapes — CONDITIONED-HARD (owner-ruled): asserted
# only when a measured status cycle exists in this run's detected cycles; the skip
# carries the Q5 `conditional-cell:` prefix so sweep accounting can partition
# designed conditioning from silent stand-downs. Populated alongside _MATCH_SHAPES
# growth as the DAT-725 elements are confirmed on the pinned engine.
_CONDITIONED_SHAPES: dict[str, str] = {}


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
