"""Agent-metadata ground-truth oracle — the DAT-680 P1 assertion-layer seed.

Loads ``calibration/fixtures/metadata_truth.yaml`` (the hand-authored ground
truth for the finance corpus) and reads the engine's persisted agent/derived
metadata from the ``current_*`` read views, so a calibration test can grade the
AGENT layer the way detectors are already graded against ``entropy_map.yaml``.

First surface (DAT-718): ``metric_additivity``. Sibling readers (relationships,
roles, cycles) land with DAT-684/685/686 — each is one ``current_*`` view read
plus a named set-statistic vs this file, following the shape below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FIXTURE = Path(__file__).parent / "fixtures" / "metadata_truth.yaml"


def load_truth() -> dict[str, Any]:
    """The parsed ``metadata_truth.yaml`` ground truth."""
    truth: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    return truth


@dataclass(frozen=True)
class AdditivityVerdict:
    """One drill target's additivity verdict — the four graded fields.

    ``None`` on a side means **not determined this run**, which is NOT the same as
    non-additive: the engine abstains with a typed reason where it cannot classify, and
    folding an abstention to ``False`` would manufacture an oracle failure out of an
    honest refusal.
    """

    categorical_additive: bool | None
    time_additive: bool | None
    categorical_reason: str | None
    time_reason: str | None


# Engine vocabulary (``ck_metric_axis_additivity_verdict``). Only 'additive' is additive;
# 'semi_additive' and 'non_additive_recompute' both mean "do not SUM this axis".
_ADDITIVE = "additive"

# The class-level axis row: the verdict for EVERY axis of its kind. A concrete column
# name in ``axis_key`` refines it (engine property_graph.py, DAT-857/868).
_CLASS_AXIS = "*"


def read_metric_additivity(session: Any) -> dict[tuple[str, str], AdditivityVerdict]:
    """Per-target additivity, folded from the per-AXIS rows the engine now emits.

    Reads the promoted operating_model head via the ``<ws>_read`` schema — the
    same ``current_*`` surface the drill (cockpit) reads, not the raw versioned
    table — so the oracle grades exactly what the product would consume.

    **Grain change (DAT-857/868).** ``metric_additivity`` became
    ``metric_axis_additivity``: one row per ``(target, axis_kind, axis_key)`` carrying
    ``status`` ∈ {classified, abstained} and, when classified, a ``verdict``. Our truth
    is still per-target-per-axis-KIND, so the rows are folded:

    * ``axis_key = '*'`` is the engine's CLASS-level row — the verdict covering every
      axis of that kind, which is exactly the grain our truth speaks at. When present
      it is used directly; a concrete column row REFINES the class and must not be
      mixed into it.
    * With no class row, the concrete axes are conjoined: **additive** iff every
      CLASSIFIED axis of that kind is ``additive``, since the drill may not SUM across
      an axis that does not sum.
    * **abstentions are never counted as False.** A kind whose axes all abstained (or
      that has no rows) is ``None`` — not determined — and the consumer reports it as
      ungrounded rather than wrong.
    * ``reason`` is the deciding non-additive row's reason, matching the old column's
      meaning ("why this kind does not sum").

    The fold loses the per-axis resolution the engine now provides. Recovering it needs
    per-axis truth in ``metadata_truth`` — a testdata change, tracked as follow-up; until
    then this grades what the truth can actually express.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT target_kind, target_key, axis_kind, axis_key, status, verdict, reason "
            f'FROM "{read_schema}".current_metric_axis_additivity'
        )
    ).all()

    by_target: dict[tuple[str, str], dict[str, list[Any]]] = {}
    for r in rows:
        target = by_target.setdefault((r.target_kind, r.target_key), {})
        target.setdefault(r.axis_kind, []).append(r)

    def fold(axes: list[Any]) -> tuple[bool | None, str | None]:
        # The class row IS the per-kind answer; concrete axes only refine it.
        class_rows = [a for a in axes if a.axis_key == _CLASS_AXIS]
        considered = class_rows or axes
        classified = [a for a in considered if a.status == "classified"]
        if not classified:
            return None, None  # abstained or absent — undetermined, never False
        non_additive = [a for a in classified if a.verdict != _ADDITIVE]
        if not non_additive:
            return True, None
        return False, next((a.reason for a in non_additive if a.reason), None)

    out: dict[tuple[str, str], AdditivityVerdict] = {}
    for key, axes_by_kind in by_target.items():
        categorical, categorical_reason = fold(axes_by_kind.get("categorical", []))
        time_additive, time_reason = fold(axes_by_kind.get("time", []))
        out[key] = AdditivityVerdict(
            categorical_additive=categorical,
            time_additive=time_additive,
            categorical_reason=categorical_reason,
            time_reason=time_reason,
        )
    return out


def expected_additivity(truth: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Flatten ``metric_additivity`` to ``(target_kind, target_key) -> spec``."""
    block = truth.get("metric_additivity") or {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for kind in ("metric", "measure"):
        for key, spec in (block.get(f"{kind}s") or {}).items():
            out[(kind, key)] = spec
    return out


def expected_folded_dimensions(truth: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``folded_dimensions`` truth (DAT-757) — empty unless the run denormalized.

    Each entry: ``{concept, source_dimension, fold_key, attributes, folded_into}``. Two
    facts sharing a ``concept`` are ONE dimension (cross-fact identity). The engine
    reader that grades against this lands with the DAT-757 folded-identity build; until
    then this flattener + the Tier-1 consistency test bind the truth to the corpus.
    """
    return list(truth.get("folded_dimensions") or [])


def expected_degenerate_ids(truth: dict[str, Any]) -> set[str]:
    """The ``degenerate_ids`` truth (DAT-757) — ``table.column`` operational PKs that
    ground to no concept and must ABSTAIN (no cross-table folded identity)."""
    return set(truth.get("degenerate_ids") or [])


def expected_bus_matrix(truth: dict[str, Any]) -> dict[str, dict[str, dict[str, str]]]:
    """The ``bus_matrix`` truth (DAT-756/757): ``{fact: {concept: {provenance, key}}}``.

    Provenance ∈ {referenced, folded, key_only}. The unifying oracle for dimension
    identity — a correct bus matrix implies correct referenced identity, folded identity,
    and cross-fact bridging at once. The engine reader (a persisted bus-matrix surface,
    per Philipp 2026-07-14 "we should persist that") lands with the DAT-756/757 builds.
    """
    return dict(truth.get("bus_matrix") or {})


def expected_groundings(truth: dict[str, Any]) -> dict[str, set[str]]:
    """``concept -> distinct relation (table) fan-in`` from ``business_concepts.required``.

    The DAT-725 enumeration truth: once P2 lands, each (concept, relation) pair
    here must be enumerable as a Grounding node. Includes single-relation concepts
    (debit, credit) — multi-grounding is the >= 2 subset carried separately in
    ``reconciles_with.multi_grounding``.
    """
    out: dict[str, set[str]] = {}
    for col, concept in ((truth.get("business_concepts") or {}).get("required") or {}).items():
        out.setdefault(str(concept), set()).add(str(col).partition(".")[0])
    return out


def expected_reconciles_with(truth: dict[str, Any]) -> dict[str, Any]:
    """The ``reconciles_with`` truth (DAT-725 P2) — the expected post-P2 edge set.

    ``aggregation_lineage``: ``[{measure: "table.column", event_table: str}]`` — the
    DAT-491 witness; its verdict lands as the measure's CONCEPT self-loop (resolve
    measure → concept via ``business_concepts.required``). ``multi_grounding``:
    ``[{concept: str, relations: [str, ...]}]`` — concepts whose required bindings fan
    into >= 2 relations; the verdict is that concept's self-loop (the groundings'
    pairwise detail stays graph-derivable, not row-materialized). Both derived by the
    generator per level (empty at ``single``, where every binding collapses into one
    relation).
    """
    block = truth.get("reconciles_with") or {}
    return {
        "aggregation_lineage": list(block.get("aggregation_lineage") or []),
        "multi_grounding": list(block.get("multi_grounding") or []),
    }


def grounding_relation_key(relation: str) -> str:
    """Normalize a grounding's served-relation name into the truth's table space.

    Strips the ``src_<digest>__`` upload prefix and an ``enriched_`` serving prefix
    (enriched_views_phase names a fact's serving view ``enriched_<fact>``), so a
    Grounding on either the typed table or its enriched serving view matches the
    truth's fact-table names.
    """
    from calibration.tools._runs import short

    return short(relation).removeprefix("enriched_")


def read_view_exists(session: Any, view_name: str) -> bool:
    """Whether the read schema exposes ``view_name`` — the pre/post-P2 capability probe."""
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    return (
        session.execute(
            text(
                "SELECT 1 FROM information_schema.views "
                "WHERE table_schema = :schema AND table_name = :view"
            ),
            {"schema": read_schema, "view": view_name},
        ).first()
        is not None
    )


def read_groundings(session: Any) -> set[tuple[str, str]]:
    """Every HEALTHY ``(concept, relation)`` pair in ``current_groundings`` (DAT-725 P2).

    The landed P2 view deliberately includes retained failures and pre-parts rows as
    first-class grounding nodes (``failed`` property / NULL relation). This reader
    grades ENUMERABLE HEALTHY groundings only — the grain the engine's own
    >= 2-groundings reconciles_with producer counts — so failed rows can never
    inflate a multi-grounding count into a false HARD demand for an edge. Relations
    are normalized through :func:`grounding_relation_key` into the truth's
    fact-table space.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            f'SELECT concept, relation FROM "{read_schema}".current_groundings '
            "WHERE NOT failed AND relation IS NOT NULL"
        )
    ).all()
    return {(str(r.concept), grounding_relation_key(str(r.relation))) for r in rows}


def read_reconciles_with(session: Any) -> list[dict[str, Any]]:
    """Active ``reconciles_with`` concept edges: ``[{from_concept, to_concept, tolerance}]``.

    Landed P2 shape (owner-ruled): derived rows are concept-grain SELF-LOOPS —
    ``from_concept == to_concept``, tolerance NULL, ONE active row per concept (a
    self-loop is its own reverse; nothing is direction-doubled). The row asserts
    "this concept's computations must tie out"; the pairing detail stays derivable
    from the ``grounded_by`` fan-out and the aggregation-lineage witness. Pre-P2 the
    only writer is the vocabulary seed, so this returns ``[]``.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT from_concept, to_concept, tolerance "
            f'FROM "{read_schema}".concept_edges '
            "WHERE predicate = 'reconciles_with' AND superseded_at IS NULL"
        )
    ).all()
    return [
        {"from_concept": r.from_concept, "to_concept": r.to_concept, "tolerance": r.tolerance}
        for r in rows
    ]


def read_extract_snippets(session: Any) -> list[dict[str, Any]]:
    """Every persisted EXTRACT snippet: ``[{snippet_id, standard_field, sql, parts}]``.

    Reads the workspace's ``sql_snippets`` KB table directly (not run-versioned; the
    graph agent is the only extract author — cockpit rows are ``snippet_type='query'``
    AND the engine's grounding surface additionally guards ``source LIKE 'graph:%'``,
    so query-SOURCED extracts are excluded there too). ``parts`` is the DAT-671
    clause-parts artifact
    ``{select: [{expr, alias}], from: [relation], where: [...]}`` that
    ``compose_extract_sql`` renders; the parts-parity oracle holds the stored ``sql``
    to exactly that render.
    """
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT snippet_id, standard_field, sql, parts FROM sql_snippets "
            "WHERE snippet_type = 'extract'"
        )
    ).all()
    return [
        {
            "snippet_id": r.snippet_id,
            "standard_field": r.standard_field,
            "sql": r.sql,
            "parts": r.parts,
        }
        for r in rows
    ]


def read_temporal_behavior(session: Any) -> dict[str, str]:
    """``current_column_concepts.temporal_behavior`` keyed ``"table.column"`` (narrow names).

    The catalogue-grain stock/flow verdict (DAT-637 re-homed it to ``ColumnConcept``)
    — the surface DAT-685 grades against ``metadata_truth.stock_flow``. Only columns
    the detector resolved (``temporal_behavior IS NOT NULL``) are returned.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS table_name, c.column_name AS column_name, "
            "cc.temporal_behavior AS temporal_behavior "
            f'FROM "{read_schema}".current_column_concepts cc '
            f'JOIN "{read_schema}".current_columns c ON c.column_id = cc.column_id '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = c.table_id '
            "WHERE cc.temporal_behavior IS NOT NULL"
        )
    ).all()
    return {f"{short(r.table_name)}.{r.column_name}": r.temporal_behavior for r in rows}


def read_structural_witness_fired(session: Any) -> tuple[int, int]:
    """``(fired, total)`` over this run's ``temporal_behavior`` entropy objects.

    ``fired`` counts objects whose structural-reconciliation witness (DAT-491)
    produced a pattern (``evidence[0].structural_pattern`` is non-null) — the
    data-grounded witness that dissents when the two name-based witnesses are
    fooled together. ``fired == 0`` with ``total > 0`` is the inert-safeguard
    signature: stock/flow decided by names alone (the DAT-720 regression).
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            f'SELECT evidence FROM "{read_schema}".current_entropy_objects '
            "WHERE detector_id = 'temporal_behavior'"
        )
    ).all()
    total = fired = 0
    for r in rows:
        evidence = r.evidence if isinstance(r.evidence, list) else []
        first = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
        total += 1
        if first.get("structural_pattern") is not None:
            fired += 1
    return fired, total


def read_structural_patterns(session: Any) -> dict[str, str]:
    """``measure_aggregation_lineage`` pattern per measure, keyed ``"table.column"``.

    The DATA-grounded stock/flow verdict for measures that reconciled against an
    event fact (DAT-491): ``per_period`` (a flow) or ``cumulative`` (a stock). This
    is deterministic where it fires — unlike the two name-based witnesses — so it's
    the surface DAT-685 can grade HARD. A measure that didn't reconcile is absent
    (name-only, LLM-variable → graded soft). Reads the head-scoped
    ``current_measure_aggregation_lineage`` view (``measure_aggregation_lineage``
    is catalog-grain like ``relationships``) — the raw table accumulates every
    run's rows, and a stale run's pattern must not leak into HARD grading (the
    same leak class ``read_defined_relationships`` fixed; senior-review find).
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS table_name, c.column_name AS column_name, "
            "mal.pattern AS pattern "
            f'FROM "{read_schema}".current_measure_aggregation_lineage mal '
            "JOIN columns c ON c.column_id = mal.measure_column_id "
            "JOIN tables t ON t.table_id = c.table_id"
        )
    ).all()
    return {f"{short(r.table_name)}.{r.column_name}": r.pattern for r in rows}


def read_defined_relationships(session: Any) -> set[tuple[str, str, str, str]]:
    """Every DEFINED relationship (``detection_method != 'candidate'``) as a directed
    edge ``(from_table, from_col, to_table, to_col)`` with narrow table names.

    The judge-confirmed FK catalog DAT-684 grades — recall (every true FK present)
    and precision (no spurious FKs). Reads ``current_relationships`` — the
    promoted-catalog-head view (the same scoping ``current_bus_matrix`` rides) —
    never the raw ``relationships`` table: multiple runs' rows coexist there (a
    teach re-run, a prior pass of the same workspace), and a stale run's confirmed
    row inflates recall with an edge the graded run never produced (run #2's false
    8/9). Name joins stay on the raw ``columns``/``tables`` — ``column_id`` is
    unique, so name resolution needs no head scoping.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT ft.table_name AS ft, fc.column_name AS fc, "
            "tt.table_name AS tt, tc.column_name AS tc "
            f'FROM "{read_schema}".current_relationships r '
            "JOIN columns fc ON fc.column_id = r.from_column_id "
            "JOIN tables ft ON ft.table_id = fc.table_id "
            "JOIN columns tc ON tc.column_id = r.to_column_id "
            "JOIN tables tt ON tt.table_id = tc.table_id "
            "WHERE r.detection_method != 'candidate'"
        )
    ).all()
    return {(short(r.ft), r.fc, short(r.tt), r.tc) for r in rows}


_FkEdge = tuple[str, str, str, str]  # (from_table, from_col, to_table, to_col)


def fk_edge_satisfies(defined: _FkEdge, true_fk: _FkEdge) -> bool:
    """One defined edge satisfies one truth edge — the ONE FK matcher.

    Same tables in the same orientation, truth column carried exactly or as a
    DAT-277 surrogate composite whose column name contains it
    (``_sk__date__payment_id`` embeds ``payment_id``). Shared by the recall
    grading (``test_relationships_e2e._satisfies``) and the miss diagnostic
    (:func:`pick_fk_miss_diagnostic`) so the two can never drift — the
    diagnostic must explain exactly what the grader graded.
    """
    dft, dfc, dtt, dtc = defined
    tft, tfc, ttt, ttc = true_fk
    return dft == tft and dtt == ttt and tfc in dfc and ttc in dtc


def pick_fk_miss_diagnostic(
    rows: list[tuple[str, str, str, str, str, float, dict[str, Any] | None]],
    pair: _FkEdge,
) -> dict[str, Any] | None:
    """The row that best explains one truth pair's recall miss (pure; Tier-1-able).

    ``rows`` are the graded run's relationship rows as ``(from_table, from_col,
    to_table, to_col, detection_method, confidence, evidence)`` with narrow table
    names; ``pair`` is the missing truth edge. Matching is
    :func:`fk_edge_satisfies` — the recall grading's own matcher. Preference:

    * a CONFIRMED (non-candidate) row in the FLIPPED orientation → ``kind:
      "confirmed_flipped"``. The judge accepted the pair but oriented it against
      the truth; grading is direction-exact so the red stands, but "DECLINED"
      would be a mis-diagnosis (run #2 printed payments↔bank_transactions,
      confirmed 0.95 flipped, as "DECLINED at 1.0").
    * else a candidate row → ``kind: "declined"`` — a real judge decline,
      auditable via its kept evidence (DAT-699). Direction-insensitive (the
      judge's orientation is not run-stable); among several matching candidate
      rows the exact-orientation one wins, then the higher confidence, so the
      printed evidence is reproducible across runs (SQL row order is not).
    * else ``None`` — the pair never became a candidate (a Layer-A gap, not a
      judge decline — a different bug class).
    """
    flipped: _FkEdge = (pair[2], pair[3], pair[0], pair[1])
    declines: list[tuple[bool, float, dict[str, Any] | None]] = []
    for rft, rfc, rtt, rtc, method, confidence, evidence in rows:
        row: _FkEdge = (rft, rfc, rtt, rtc)
        if method != "candidate":
            if fk_edge_satisfies(row, flipped):
                return {"kind": "confirmed_flipped", "confidence": confidence, "evidence": evidence}
            continue
        exact = fk_edge_satisfies(row, pair)
        if exact or fk_edge_satisfies(row, flipped):
            declines.append((exact, confidence, evidence))
    if not declines:
        return None
    _, confidence, evidence = max(declines, key=lambda d: (d[0], d[1]))
    return {"kind": "declined", "confidence": confidence, "evidence": evidence}


def read_fk_miss_diagnostic(
    session: Any, from_table: str, from_col: str, to_table: str, to_col: str
) -> dict[str, Any] | None:
    """Why one truth FK is missing, explained from the graded run's own rows.

    Reads ALL of ``current_relationships`` (confirmed + candidate) — head-scoped
    like :func:`read_defined_relationships`, so the explanation describes THIS
    run, never a stale one — and delegates the choice to
    :func:`pick_fk_miss_diagnostic` (see there for the kinds and preference).
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT ft.table_name AS ft, fc.column_name AS fc, "
            "tt.table_name AS tt, tc.column_name AS tc, "
            "r.detection_method AS method, "
            "r.confidence AS confidence, r.evidence AS evidence "
            f'FROM "{read_schema}".current_relationships r '
            "JOIN columns fc ON fc.column_id = r.from_column_id "
            "JOIN tables ft ON ft.table_id = fc.table_id "
            "JOIN columns tc ON tc.column_id = r.to_column_id "
            "JOIN tables tt ON tt.table_id = tc.table_id"
        )
    ).all()
    return pick_fk_miss_diagnostic(
        [(short(r.ft), r.fc, short(r.tt), r.tc, r.method, r.confidence, r.evidence) for r in rows],
        (from_table, from_col, to_table, to_col),
    )


def expected_relationships(truth: dict[str, Any]) -> dict[tuple[str, str, str, str], bool]:
    """``relationships`` truth as ``(from_table, from_col, to_table, to_col) -> direction_reliable``.

    ``direction_reliable=False`` means a merge destroyed the parent side's grain
    (e.g. ``journal_entries.entry_id`` repeats per general_ledger line at flat),
    so the engine's uniqueness-canonical orientation (#495 many→one) may
    legitimately flip — grade the edge in EITHER direction (Philipp's ruling,
    2026-07-16). An absent flag (canonical/full truth) means reliable.
    """
    out: dict[tuple[str, str, str, str], bool] = {}
    for rel in truth.get("relationships") or []:
        ft, fc = str(rel["from"]).split(".", 1)
        tt, tc = str(rel["to"]).split(".", 1)
        out[(ft, fc, tt, tc)] = bool(rel.get("direction_reliable", True))
    return out


def read_table_entities(session: Any) -> dict[str, dict[str, Any]]:
    """``current_table_entities`` per table (narrow name): ``{role, is_fact,
    is_dimension, entity_type}``.

    The table-level role surface DAT-685 grades — ``table_role`` (DAT-728:
    fact | periodic_snapshot | dimension, replacing the two booleans) HARD where
    structure decides it, ``detected_entity_type`` reported (free text, no
    ontology vocabulary). ``is_fact``/``is_dimension`` are derived here so the
    grading semantics stay put: a measure-bearing periodic snapshot IS a fact
    table for role-accuracy purposes.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS tn, te.table_role AS role, "
            "te.detected_entity_type AS et "
            f'FROM "{read_schema}".current_table_entities te '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = te.table_id'
        )
    ).all()
    return {
        short(r.tn): {
            "role": r.role,
            "is_fact": r.role in ("fact", "periodic_snapshot"),
            "is_dimension": r.role == "dimension",
            "entity_type": r.et,
        }
        for r in rows
    }


def read_semantic_roles(session: Any) -> dict[str, str]:
    """``current_semantic_annotations.semantic_role`` keyed ``"table.column"`` (narrow).

    The per-column role ∈ {key, measure, dimension, timestamp, attribute} DAT-685
    grades — measure/timestamp HARD, the rest reported.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS tn, c.column_name AS cn, sa.semantic_role AS role "
            f'FROM "{read_schema}".current_semantic_annotations sa '
            f'JOIN "{read_schema}".current_columns c ON c.column_id = sa.column_id '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = c.table_id'
        )
    ).all()
    return {f"{short(r.tn)}.{r.cn}": r.role for r in rows}


def read_column_meanings(session: Any) -> dict[str, str]:
    """Non-null ``current_column_concepts.meaning`` keyed ``"table.column"`` (DAT-769).

    The binding oracle is RETIRED (grade consumers, not mappings — DAT-769); this
    read supports the meaning-PRESENCE smoke only. Meaning contents are never
    graded against fixed strings.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS tn, c.column_name AS cn, cc.meaning AS bc "
            f'FROM "{read_schema}".current_column_concepts cc '
            f'JOIN "{read_schema}".current_columns c ON c.column_id = cc.column_id '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = c.table_id '
            "WHERE cc.meaning IS NOT NULL"
        )
    ).all()
    return {f"{short(r.tn)}.{r.cn}": r.bc for r in rows}


@dataclass(frozen=True)
class MeaningRow:
    """One eligible catalogue column and its ColumnConcept meaning coverage (DAT-853/DAT-823).

    ``has_concept`` — a ``column_concepts`` row exists for the column (LEFT-JOIN hit).
    ``meaning`` — the free-text meaning (NULL/blank = none authored; the engine coerces a
    whitespace-only meaning to NULL at write). ``meaning_status`` — the DAT-823 split's status
    (NULL on pre-split rows, ``'determined'``/``'ambiguous'`` post-split; ``'ambiguous'`` still
    counts as covered — declared ignorance WITH a meaning present).
    """

    column: str
    has_concept: bool
    meaning: str | None
    meaning_status: str | None


def meaning_status_present(session: Any) -> bool:
    """Whether ``current_column_concepts`` exposes the DAT-823 ``meaning_status`` column.

    The pre/post-split capability probe for the semantic-authoring split (DAT-823 W3-F): the
    column does not exist on today's engine, so the coverage-parity oracle stands down until
    the split lands — the ADR-0022 oracle-first pattern (written BEFORE the engine cut, like
    ``read_view_exists`` gates the P2 grounding oracles).
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    return (
        session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'current_column_concepts' "
                "AND column_name = 'meaning_status'"
            ),
            {"schema": read_schema},
        ).first()
        is not None
    )


def read_meaning_coverage(session: Any) -> list[MeaningRow]:
    """Every eligible catalogue column with its ColumnConcept meaning + status (LEFT JOIN).

    Eligible = every column of the catalogue tables — the coverage universe the engine's own
    authoring targets (no id/type exclusion; only 100%-null columns are dropped upstream by
    ``column_eligibility`` and never reach the catalogue). A column with no concept row, or a
    NULL/blank meaning, is a coverage gap. ``meaning_status`` rides through for reporting;
    ``'ambiguous'`` counts as covered. Call only after :func:`meaning_status_present` — the
    SELECT references the DAT-823 column.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS tn, c.column_name AS cn, cc.concept_id AS concept_id, "
            "cc.meaning AS meaning, cc.meaning_status AS meaning_status "
            f'FROM "{read_schema}".current_columns c '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = c.table_id '
            f'LEFT JOIN "{read_schema}".current_column_concepts cc ON cc.column_id = c.column_id'
        )
    ).all()
    return [
        MeaningRow(
            column=f"{short(r.tn)}.{r.cn}",
            has_concept=r.concept_id is not None,
            meaning=r.meaning,
            meaning_status=r.meaning_status,
        )
        for r in rows
    ]


def read_driver_rankings(session: Any) -> dict[str, dict[str, Any]]:
    """``current_driver_rankings`` per measure column, keyed ``"table.column"`` (narrow).

    Each value is the persisted :class:`DriverRanking` surface DAT-688 grades:
    ``{measure_label, target_type, grain, entity, n_rows, ranked_dimensions,
    interesting_slices, secondary_dimensions}`` — ``ranked_dimensions`` a list of
    ``(dimension, gain)`` (the primary family's significant dims, strongest first) and
    ``interesting_slices`` a list of ``{dimension, value, effect, support}`` (sharp
    slices across the tree). Read from the promoted head's ``current_*`` view — exactly
    what the answer agent's ``look_drivers`` consumes.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS tn, c.column_name AS cn, dr.measure_label AS ml, "
            "dr.target_type AS tt, dr.grain AS grain, dr.entity AS entity, "
            "dr.n_rows AS n_rows, dr.ranked_dimensions AS ranked, "
            "dr.interesting_slices AS slices, dr.secondary_dimensions AS secondary, "
            "dr.status AS status, dr.abstain_reason AS abstain_reason "
            f'FROM "{read_schema}".current_driver_rankings dr '
            f'JOIN "{read_schema}".current_columns c ON c.column_id = dr.measure_column_id '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = dr.measure_table_id'
        )
    ).all()
    return {
        f"{short(r.tn)}.{r.cn}": {
            "measure_label": r.ml,
            "target_type": r.tt,
            "grain": r.grain,
            "entity": r.entity,
            "n_rows": r.n_rows,
            # JSON columns arrive parsed; ranked as [(dim, gain)] for ergonomic reads.
            "ranked_dimensions": [
                (d["dimension"], d["gain"]) for d in (r.ranked or [])
            ],
            "interesting_slices": list(r.slices or []),
            "secondary_dimensions": list(r.secondary or []),
            # DAT-725 rewiring: rankings carry status/abstain_reason. An ABSTAINED
            # row is coverage evidence, not a measured-empty ranking — consumers
            # must split on status (the DAT-853 abstention rule, same class).
            "status": r.status,
            "abstain_reason": r.abstain_reason,
        }
        for r in rows
    }


def read_detected_cycles(session: Any) -> list[dict[str, Any]]:
    """Detected business cycles from ``current_detected_business_cycles``.

    Each is ``{canonical_type, cycle_name, is_known_type, confidence, tables}`` with
    ``tables`` a set of narrow table names. The LLM-inferred process cycles DAT-686
    grades — recall of the corpus's backbone cycles + legitimacy (known type, real
    tables) of what was detected.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT canonical_type, cycle_name, is_known_type, confidence, tables_involved, "
            "family, direction, status_column, completion_value, completion_rate "
            f'FROM "{read_schema}".current_detected_business_cycles'
        )
    ).all()
    return [
        {
            "canonical_type": r.canonical_type,
            "cycle_name": r.cycle_name,
            "is_known_type": bool(r.is_known_type),
            "confidence": r.confidence,
            "tables": {short(t) for t in (r.tables_involved or [])},
            # DAT-856 direction surface (engine CHECK: family/direction both-null-
            # or-both-set; Cut B renders an undirected detection as canonical_type
            # = the family with direction='undetermined').
            "family": r.family,
            "direction": r.direction,
            # the measured-status surface (O4's conditioned-hard condition reads
            # the same rows; exposed here so there is one loader, not two).
            "status_column": r.status_column,
            "completion_value": r.completion_value,
            "completion_rate": r.completion_rate,
        }
        for r in rows
    ]


def is_wild(truth: dict[str, Any]) -> bool:
    """Is this a Tier-B (wild) corpus — declared structure only?

    Tier B carries an external corpus's OWN declared truth: foreign keys, types,
    time columns. It declares no measures, no business concepts, no metrics —
    those would be our reading of someone else's schema, not their statement about
    it (``entropy_eval_architecture.md``, the corpus policy).

    So an oracle whose truth section is absent on a wild corpus must STAND DOWN,
    not fail: there is nothing to be right or wrong about. That is the opposite of
    Tier A, where an absent section IS a defect (the DAT-725 "absence falls loud"
    invariant) because the generator always authors it. The flag is written by
    ``scripts/stage_wild_corpus.py``; a corpus with no ``tier`` is Tier A, so the
    loud-by-default behaviour is unchanged for every existing strategy.
    """
    return str(truth.get("tier") or "").lower() == "wild"
