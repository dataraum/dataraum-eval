"""Grounding-substrate oracles — the DAT-725 Layer-1 scorecard on a real finance run.

Grades the P2 grounding reification (Grounding node per (concept, relation),
``grounded_by`` / ``uses`` graph edges, ``reconciles_with`` population) and the
truth-free snippet parts-parity invariant against the shapes P2 will emit. Written
BEFORE the engine cutting starts (oracle-first, ADR-0022): every test that needs a
P2 surface probes for it and SKIPS on a pre-P2 engine — but once the surface
exists, absence falls loud (an empty grounding batch is a stop-condition, never a
green run; an element view with rows that never instantiates in a MATCH is a
binding defect).

Assumed P2 contract (from the DAT-725 owner ledger; each assumption is a single,
documented adaptation seam if the P2 lane lands different names):

* read view ``current_groundings`` with concept NAME ``concept`` + served relation
  ``relation`` columns (the view name is locked by the lane brief; the reader seam
  is ``calibration.metadata_truth.read_groundings``);
* element views ``og_grounding`` / ``og_grounded_by`` / ``og_uses`` with PGQ labels
  ``grounding_node`` (vertex), ``grounded_by`` (concept → grounding), ``uses``
  (grounding → column), following the existing ``og_*`` label convention;
* ``reconciles_with`` verdicts readable as active ``concept_edges`` rows
  (``ConceptEdgePredicate.RECONCILES_WITH``, symmetric, both directions).

Determinism split (the anti-Goodhart grammar):

* **structural = HARD** — parts parity (``compose_extract_sql(parts) == sql``),
  batch non-emptiness once a P2 surface exists, MATCH-returns-rows, and the
  deterministic >= 2-groundings reconciliation producer firing at all.
* **LLM-dependent = in-body xfail (strict=False semantics)** — per-(concept,
  relation) enumeration completeness and per-concept reconciliation coverage
  depend on metric-grounding recall (the metrics-phase LLM), so a shortfall is a
  diagnostic for that lane, never a hard build-break here. Flip-to-hard is the
  DAT-736 close-out rebaseline's call, not this file's.

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``; pytest auto-collects.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import (
    expected_groundings,
    expected_reconciles_with,
    read_extract_snippets,
    read_groundings,
    read_reconciles_with,
    read_view_exists,
)
from calibration.tools._runs import workspace_session

# The P2 property-graph elements and the MATCH each must instantiate in. The
# capability probe is the element VIEW's existence; the assertion is the graph
# BINDING (a view can hold rows whose keys dangle — only a MATCH proves the edge).
_P2_MATCH_SHAPES: dict[str, str] = {
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

_EMPTY_BATCH = (
    "current_groundings exists but the grounding batch is EMPTY — a stop-condition "
    "(absence falls loud, DAT-725 invariant), never a green run"
)


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    """Skip without a completed run; otherwise activate the strategy's workspace."""
    sidecar = runner_mod.sidecar_path(strategy_name)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {strategy_name!r}; run "
            f"`python -m calibration.run -s {strategy_name}` first"
        )
    runner_mod.activate_workspace(strategy_name)


def _read_schema(session: Any) -> str:
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    return read_schema_name_for(str(session.execute(text("SELECT current_schema()")).scalar()))


# --- (c) parts parity — structural, HARD, truth-free -------------------------


@pytest.mark.llm
def test_extract_snippet_parts_parity(strategy_name: str) -> None:
    """Every persisted EXTRACT snippet's ``parts`` re-render EXACTLY the stored sql.

    ``parts`` is the persisted artifact and ``sql`` its one-time render
    (``compose_extract_sql``, DAT-671 parts-at-source) — any divergence means a
    second authoring path wrote one of them, the exact drift the parts contract
    exists to prevent. Truth-free and label-invariant: HARD. A NULL ``parts`` on a
    fresh eval run is the same defect (the legacy NULL-parts carve-out covers only
    rows authored before the DAT-671 cut — an eval workspace has none).
    """
    from dataraum.graphs.formula_composer import compose_extract_sql

    with workspace_session() as session:
        snippets = read_extract_snippets(session)

    if not snippets:
        pytest.skip(
            "no extract snippets persisted — the metrics phase (operating_model "
            "workflow) did not run or produced nothing (the /smoke grounding lane, "
            "not this oracle)"
        )

    failures: list[str] = []
    for snip in snippets:
        label = f"{snip['snippet_id']} ({snip['standard_field']})"
        parts = snip["parts"]
        if not isinstance(parts, dict):
            failures.append(f"  {label}: parts is {parts!r} — extract persisted without parts")
            continue
        select = parts.get("select") or []
        if len(select) != 1:
            failures.append(f"  {label}: malformed parts.select {select!r}")
            continue
        entry = select[0] if isinstance(select[0], dict) else {}
        expr, alias = entry.get("expr"), entry.get("alias")
        if not expr or alias != "value":
            # A malformed entry is a per-snippet FAILURE, never a KeyError crash;
            # the alias is part of the contract (the cockpit drill builder composes
            # variants from parts, aliasing the scalar `value`) — parity of the
            # rendered sql alone cannot catch a wrong alias, so check it here.
            failures.append(
                f"  {label}: malformed parts.select entry {select[0]!r} (need expr + alias 'value')"
            )
            continue
        relations = parts.get("from") or []
        recomposed = compose_extract_sql(
            str(expr),
            str(relations[0]) if relations else None,
            [str(p) for p in (parts.get("where") or [])],
        )
        if recomposed != snip["sql"]:
            failures.append(
                f"  {label}:\n    stored:     {snip['sql']!r}\n    recomposed: {recomposed!r}"
            )

    print(f"\n[parts parity] {len(snippets)} extract snippets, {len(failures)} divergent")
    assert not failures, (
        "extract snippet parts do not re-render the stored sql — a second authoring "
        "path violated the DAT-671 parts-at-source contract:\n" + "\n".join(failures)
    )


# --- (d) MATCH-shape capability tests — structural, HARD ----------------------


@pytest.mark.llm
@pytest.mark.parametrize("element", sorted(_P2_MATCH_SHAPES))
def test_p2_element_instantiates_in_match(element: str, strategy_name: str) -> None:
    """A present P2 element view has rows AND those rows instantiate in a PGQ MATCH.

    View absent -> skip (pre-P2 engine). View present but empty on the finance
    corpus -> FAIL (absence falls loud). Rows present but the MATCH returns none ->
    FAIL (the element's keys dangle against its vertex tables — the binding defect
    the every-bound-edge-ships-a-MATCH-test invariant exists to catch).
    """
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, element):
            pytest.skip(f"{element} element view absent — pre-P2 engine")
        read_schema = _read_schema(session)
        direct = session.execute(
            text(f'SELECT count(*) FROM "{read_schema}".{element}')  # noqa: S608 (fixed names)
        ).scalar()
        assert direct, (
            f"{element} exists but has ZERO rows on the finance corpus — an empty "
            "grounding substrate is a stop-condition (absence falls loud), never a green run"
        )
        graph = f'"{read_schema}".operating_model'
        matched = session.execute(text(_P2_MATCH_SHAPES[element].format(graph=graph))).scalar()

    print(f"\n[match shape] {element}: {direct} view rows, {matched} MATCH rows")
    assert matched, (
        f"{element} holds {direct} rows but its MATCH returns none — the element never "
        "instantiates in the property graph (dangling keys or a label/binding mismatch)"
    )


# --- (b) grounding enumeration oracle ----------------------------------------


@pytest.mark.llm
def test_grounding_enumeration_oracle(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """Each (concept, relation) fan-in in ``business_concepts.required`` is enumerable
    as a Grounding through ``current_groundings`` (DAT-725 P2).

    HARD: the view, once present, returns a non-empty batch. Diagnostic (in-body
    xfail): per-pair completeness — a missing pair is metric-grounding recall
    (LLM-dependent), graded in its own lane. Extra groundings beyond the required
    truth are legitimate (concept selection beyond ``required`` is LLM-selective).
    """
    with workspace_session() as session:
        if not read_view_exists(session, "current_groundings"):
            pytest.skip("current_groundings absent — pre-P2 engine")
        actual = read_groundings(session)

    assert actual, _EMPTY_BATCH

    expected_pairs = {
        (concept, relation)
        for concept, relations in expected_groundings(metadata_truth).items()
        for relation in relations
    }
    missing = sorted(expected_pairs - actual)
    covered = len(expected_pairs) - len(missing)
    print(
        f"\n[grounding enumeration] {covered}/{len(expected_pairs)} required pairs "
        f"enumerated on {strategy_name}; {len(actual)} groundings total"
    )
    for concept, relation in sorted(expected_pairs):
        mark = "✓" if (concept, relation) in actual else "✗"
        print(f"  {mark} {concept:<20} @ {relation}")

    if missing:
        pytest.xfail(
            "required (concept, relation) groundings not enumerated — metric-grounding "
            f"recall (LLM-dependent), not a P2 structural defect: {missing}"
        )


@pytest.mark.llm
def test_multi_grounding_enumeration(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """Every expected multi-grounding concept enumerates >= 2 Groundings covering its
    truth relations (the scorecard's account_balance across trial_balance/
    balance_sheet). Coverage is LLM-dependent -> in-body xfail on shortfall.
    """
    multi = expected_reconciles_with(metadata_truth)["multi_grounding"]
    if not multi:
        pytest.skip("this corpus shape has no multi-grounding concept (single-relation merge)")

    with workspace_session() as session:
        if not read_view_exists(session, "current_groundings"):
            pytest.skip("current_groundings absent — pre-P2 engine")
        actual = read_groundings(session)

    assert actual, _EMPTY_BATCH

    shortfalls: list[str] = []
    for spec in multi:
        concept, want = spec["concept"], set(spec["relations"])
        got = {relation for c, relation in actual if c == concept}
        status = "✓" if want <= got else "✗"
        print(f"  {status} {concept}: expected {sorted(want)}, enumerated {sorted(got)}")
        if not want <= got:
            shortfalls.append(f"{concept}: {sorted(got)} does not cover {sorted(want)}")

    if shortfalls:
        pytest.xfail(
            "multi-grounding fan-in not fully enumerated — metric-grounding recall "
            "(LLM-dependent): " + "; ".join(shortfalls)
        )


# --- (a) reconciles_with population -------------------------------------------


@pytest.mark.llm
def test_reconciles_with_population(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """P2's reconciles_with producers fire on the finance corpus.

    HARD: if this run DID multi-ground some concept (>= 2 groundings enumerated),
    the deterministic >= 2-groundings producer must have emitted at least one
    reconciles_with edge — zero edges then is a P2 producer defect, not recall.
    Diagnostic (in-body xfail): per-concept coverage of the truth's expected
    reconciling concepts (multi-grounding + witness-reified) — those need the
    groundings to exist first, which is LLM-dependent recall.
    """
    with workspace_session() as session:
        if not read_view_exists(session, "current_groundings"):
            pytest.skip("current_groundings absent — pre-P2 engine")
        groundings = read_groundings(session)
        edges = read_reconciles_with(session)

    assert groundings, _EMPTY_BATCH

    multi_grounded = {
        concept
        for concept in {c for c, _ in groundings}
        if len({r for c, r in groundings if c == concept}) >= 2
    }
    # symmetric predicates are materialized in BOTH directions, so the row count
    # is 2x the logical reconciliation count — report it as directed rows.
    print(
        f"\n[reconciles_with] {len(edges)} active directed edge rows; multi-grounded "
        f"concepts in this run: {sorted(multi_grounded)}"
    )
    assert not (multi_grounded and not edges), (
        f"concepts {sorted(multi_grounded)} enumerate >= 2 groundings but ZERO "
        "reconciles_with edges exist — the deterministic >= 2-groundings producer "
        "did not fire (a P2 defect, not grounding recall)"
    )

    truth = expected_reconciles_with(metadata_truth)
    required = (metadata_truth.get("business_concepts") or {}).get("required") or {}
    expected_concepts = {m["concept"] for m in truth["multi_grounding"]} | {
        required[e["measure"]] for e in truth["aggregation_lineage"] if e["measure"] in required
    }
    involved = {e["from_concept"] for e in edges} | {e["to_concept"] for e in edges}
    uncovered = sorted(expected_concepts - involved)
    for concept in sorted(expected_concepts):
        print(f"  {'✓' if concept in involved else '✗'} {concept}")
    if uncovered:
        pytest.xfail(
            "expected reconciling concepts carry no reconciles_with verdict — their "
            f"groundings are LLM-recall-dependent: {uncovered}"
        )


# --- (e) served-context / AP oracle (DAT-734 AC, pending P9) ------------------


@pytest.mark.llm
def test_served_context_ap_oracle(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """The accounts_payable-class case surfaces BOTH groundings + their reconciliation.

    DAT-734's AC at the structurally-checkable core: the AP-class concept — one that
    is BOTH multi-grounded (a GL-side and a snapshot/subledger relation) AND
    witness-reconciled (aggregation lineage) — must enumerate all its groundings and
    carry a reconciles_with verdict, because that is exactly what the P9 served
    context surfaces to the agent. In-body xfail until the P9 cutover lands; the
    LLM-dependent serving effect itself (context quality) is never graded hard here.
    """
    truth = expected_reconciles_with(metadata_truth)
    required = (metadata_truth.get("business_concepts") or {}).get("required") or {}
    lineage_concepts = {
        required[e["measure"]] for e in truth["aggregation_lineage"] if e["measure"] in required
    }
    ap_class = {m["concept"] for m in truth["multi_grounding"]} & lineage_concepts
    if not ap_class:
        pytest.skip("corpus shape has no AP-class concept (multi-grounded AND witness-reconciled)")

    with workspace_session() as session:
        if not read_view_exists(session, "current_groundings"):
            pytest.xfail(
                "current_groundings absent — P2 not landed; the served-context AP "
                "oracle activates with the P9 cutover (DAT-734)"
            )
        groundings = read_groundings(session)
        edges = read_reconciles_with(session)

    # The file's own contract applies here too: once the view exists, an empty
    # batch is a HARD stop-condition — never an xfail that muddies the P9 signal.
    assert groundings, _EMPTY_BATCH

    problems: list[str] = []
    for concept in sorted(ap_class):
        want = next(
            set(m["relations"]) for m in truth["multi_grounding"] if m["concept"] == concept
        )
        got = {relation for c, relation in groundings if c == concept}
        if not want <= got:
            problems.append(f"{concept}: groundings {sorted(got)} do not cover {sorted(want)}")
        if not any(concept in (e["from_concept"], e["to_concept"]) for e in edges):
            problems.append(f"{concept}: no reconciles_with verdict present")

    print(f"\n[AP served-context] concepts={sorted(ap_class)} problems={problems or 'none'}")
    if problems:
        pytest.xfail(
            "AP-class served-context effect not yet realized (pending the P9 cutover "
            "and/or LLM grounding recall): " + "; ".join(problems)
        )
