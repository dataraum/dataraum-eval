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
    """One drill target's additivity verdict — the four graded fields."""

    categorical_additive: bool
    time_additive: bool
    categorical_reason: str | None
    time_reason: str | None


def read_metric_additivity(session: Any) -> dict[tuple[str, str], AdditivityVerdict]:
    """Every ``current_metric_additivity`` row, keyed ``(target_kind, target_key)``.

    Reads the promoted operating_model head via the ``<ws>_read`` schema — the
    same ``current_*`` surface the drill (cockpit) reads, not the raw versioned
    table — so the oracle grades exactly what the product would consume.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT target_kind, target_key, categorical_additive, time_additive, "
            "categorical_reason, time_reason "
            f'FROM "{read_schema}".current_metric_additivity'
        )
    ).all()
    return {
        (r.target_kind, r.target_key): AdditivityVerdict(
            categorical_additive=bool(r.categorical_additive),
            time_additive=bool(r.time_additive),
            categorical_reason=r.categorical_reason,
            time_reason=r.time_reason,
        )
        for r in rows
    }


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
    (name-only, LLM-variable → graded soft).
    """
    from sqlalchemy import text

    from calibration.tools._runs import short

    rows = session.execute(
        text(
            "SELECT t.table_name AS table_name, c.column_name AS column_name, "
            "mal.pattern AS pattern "
            "FROM measure_aggregation_lineage mal "
            "JOIN columns c ON c.column_id = mal.measure_column_id "
            "JOIN tables t ON t.table_id = c.table_id"
        )
    ).all()
    return {f"{short(r.table_name)}.{r.column_name}": r.pattern for r in rows}


def read_defined_relationships(session: Any) -> set[tuple[str, str, str, str]]:
    """Every DEFINED relationship (``detection_method != 'candidate'``) as a directed
    edge ``(from_table, from_col, to_table, to_col)`` with narrow table names.

    The judge-confirmed FK catalog DAT-684 grades — recall (every true FK present)
    and precision (no spurious FKs). Reads the run's ``relationships`` table directly
    (relationships have no ``current_*`` read view), so it reflects exactly what the
    downstream consumers (lineage, cycles, enriched_views, …) treat as "the FKs".
    """
    from sqlalchemy import text

    from calibration.tools._runs import short

    rows = session.execute(
        text(
            "SELECT ft.table_name AS ft, fc.column_name AS fc, "
            "tt.table_name AS tt, tc.column_name AS tc "
            "FROM relationships r "
            "JOIN columns fc ON fc.column_id = r.from_column_id "
            "JOIN tables ft ON ft.table_id = fc.table_id "
            "JOIN columns tc ON tc.column_id = r.to_column_id "
            "JOIN tables tt ON tt.table_id = tc.table_id "
            "WHERE r.detection_method != 'candidate'"
        )
    ).all()
    return {(short(r.ft), r.fc, short(r.tt), r.tc) for r in rows}


def read_candidate_relationship(
    session: Any, from_table: str, from_col: str, to_table: str, to_col: str
) -> dict[str, Any] | None:
    """The judge-DECLINED row for one pair, if any: ``{confidence, evidence}``.

    Diagnostic for a recall miss: since DAT-699 a declined pair persists as
    ``detection_method='candidate'`` with the judge's evidence/reasoning kept — so
    a flaked decline is auditable in the failing run itself. Narrow table names;
    direction-insensitive (the judge's orientation is not run-stable). Returns
    None when the pair never became a candidate (a Layer-A gap, not a judge
    decline — a different bug class).
    """
    from sqlalchemy import text

    from calibration.tools._runs import short

    rows = session.execute(
        text(
            "SELECT ft.table_name AS ft, fc.column_name AS fc, "
            "tt.table_name AS tt, tc.column_name AS tc, "
            "r.confidence AS confidence, r.evidence AS evidence "
            "FROM relationships r "
            "JOIN columns fc ON fc.column_id = r.from_column_id "
            "JOIN tables ft ON ft.table_id = fc.table_id "
            "JOIN columns tc ON tc.column_id = r.to_column_id "
            "JOIN tables tt ON tt.table_id = tc.table_id "
            "WHERE r.detection_method = 'candidate'"
        )
    ).all()
    want = {(from_table, from_col, to_table, to_col), (to_table, to_col, from_table, from_col)}
    for r in rows:
        if (short(r.ft), r.fc, short(r.tt), r.tc) in want:
            return {"confidence": r.confidence, "evidence": r.evidence}
    return None


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
            "dr.interesting_slices AS slices, dr.secondary_dimensions AS secondary "
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
            "SELECT canonical_type, cycle_name, is_known_type, confidence, tables_involved "
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
        }
        for r in rows
    ]
