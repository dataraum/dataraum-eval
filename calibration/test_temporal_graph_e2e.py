"""Temporal coverage, grain, anchor & calendar — the O1 graph oracle (P5/DAT-730).

Grades the promoted graph's temporal surface (GRAPH_TABLE MATCH over the og_*
elements, never raw tables) against the run's OWN declarations and profiles —
engine-internal parity, so it needs no corpus truth files and grades Tier-A and
Tier-B alike:

1. **Coverage shape (HARD)** — one ``temporal_coverage`` edge per (relation,
   declared time column) in ``table_entities.time_columns``; ``observed_grain`` ==
   ``temporal_column_profiles.detected_granularity`` (NEVER the
   ``measure_aggregation_lineage.period_grain`` config echo — equality with the
   profile is what catches that projection defect); observed window == the
   profile's window.
2. **Absence falls loud (HARD)** — irregular/unknown grain ⇒ completeness_ratio /
   expected/actual_periods / last_period_complete all NULL on the edge (never
   0 / 1.0); a declared-but-unprofiled time column keeps its edge with NULL
   observed_* (never a synthesized "complete"). Known sensitivity ceiling
   (detection.py): the trailing-partial mechanism catches truncated tails, not
   merely-short tails — this oracle asserts the NULL-contract and reports
   last_period_complete, it does not demand finer resolution than the mechanism
   defines.
3. **Anchor one-home (HARD)** — ``og_columns.anchor_time_axis`` == the lineage
   witness's axis where a witness reconciled the measure, else the single declared
   ``is_anchor`` event column; never positional.
4. **Roll-up (HARD)** — the period ladder day→month→quarter→year is exactly the
   three ``period_rolls_up_to`` edges with ascending ordinals;
   ``rolls_up_to`` edges reproduce each drilldown hierarchy's level order
   (finer→coarser, level n → n-1); alias/role hierarchies emit none.
5. **Calendar stamped (HARD)** — unset workspace ⇒ ``fiscal_year_start_month=1``
   + ``calendar_source='default'`` (visible, never silent); declared ⇒ follows
   the declaration with ``calendar_source='declared'``.

Q4 ruling: one module (both halves bind the identical cube cell). Tier-3
(docker + Temporal + LLM upstream): marked ``llm``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import read_view_exists
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="begin_session")

_GRAINED = frozenset({"second", "minute", "hour", "day", "week", "month", "quarter", "year"})


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    require_pipeline_run(strategy_name)


def _read_schema(session: Any) -> str:
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    return read_schema_name_for(str(session.execute(text("SELECT current_schema()")).scalar()))


def _coverage_edges(session: Any, read_schema: str) -> list[Any]:
    from sqlalchemy import text

    graph = f'"{read_schema}".operating_model'
    rows = session.execute(
        text(
            f"SELECT * FROM GRAPH_TABLE ({graph} "
            "MATCH (t IS table_node)-[tc IS temporal_coverage]->(c IS column_node) "
            "COLUMNS (t.table_name AS table_name, tc.column_name AS column_name, "
            "tc.role AS role, tc.declared_anchor AS declared_anchor, "
            "tc.observed_grain AS observed_grain, tc.observed_min AS observed_min, "
            "tc.observed_max AS observed_max, tc.completeness_ratio AS completeness_ratio, "
            "tc.expected_periods AS expected_periods, tc.actual_periods AS actual_periods, "
            "tc.last_period_complete AS last_period_complete, tc.is_stale AS is_stale))"
        )
    ).all()
    return list(rows)


def _declared_time_columns(session: Any, read_schema: str) -> dict[str, list[dict[str, Any]]]:
    """table_name → its declared time_columns entries ({column, role, aspect, is_anchor})."""
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT t.table_name AS table_name, te.time_columns AS time_columns "
            f'FROM "{read_schema}".current_table_entities te '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = te.table_id '
            "WHERE te.time_columns IS NOT NULL"
        )
    ).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cols = r.time_columns if isinstance(r.time_columns, list) else json.loads(r.time_columns)
        if cols:
            out[r.table_name] = cols
    return out


def _profiles(session: Any, read_schema: str) -> dict[tuple[str, str], Any]:
    """(table_name, column_name) → temporal profile row."""
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT t.table_name AS table_name, c.column_name AS column_name, p.* "
            f'FROM "{read_schema}".current_temporal_column_profiles p '
            "JOIN columns c ON c.column_id = p.column_id "
            "JOIN tables t ON t.table_id = c.table_id"
        )
    ).all()
    return {(r.table_name, r.column_name): r for r in rows}


@pytest.mark.llm
def test_temporal_coverage_shape_and_grain(strategy_name: str) -> None:
    """One edge per declared (relation, time column); observed_grain == the PROFILE's
    detected_granularity; observed window == the profile's window."""
    with workspace_session() as session:
        if not read_view_exists(session, "og_temporal_coverage"):
            pytest.skip("og_temporal_coverage absent — pre-cutover engine")
        read_schema = _read_schema(session)
        edges = _coverage_edges(session, read_schema)
        declared = _declared_time_columns(session, read_schema)
        profiles = _profiles(session, read_schema)

    if not declared:
        pytest.skip("no table declares time_columns on this corpus")

    edge_keys = {(e.table_name, e.column_name) for e in edges}
    declared_keys = {(t, c["column"]) for t, cols in declared.items() for c in cols}
    missing = sorted(declared_keys - edge_keys)
    extra = sorted(edge_keys - declared_keys)
    print(f"\n[coverage shape] declared={len(declared_keys)} edges={len(edge_keys)}")
    assert not missing, f"declared time columns with NO temporal_coverage edge: {missing}"
    assert not extra, f"temporal_coverage edges with no declaration behind them: {extra}"
    assert len(edges) == len(edge_keys), "duplicate temporal_coverage edges for one (relation, column)"

    grain_mismatches: list[str] = []
    for e in edges:
        prof = profiles.get((e.table_name, e.column_name))
        if prof is None:
            continue  # unprofiled declared column — graded by the NULL-contract test
        if e.observed_grain != prof.detected_granularity:
            grain_mismatches.append(
                f"{e.table_name}.{e.column_name}: edge={e.observed_grain!r} "
                f"profile={prof.detected_granularity!r}"
            )
        if e.observed_min != prof.min_timestamp or e.observed_max != prof.max_timestamp:
            grain_mismatches.append(
                f"{e.table_name}.{e.column_name}: window drifts from the profile"
            )
    assert not grain_mismatches, (
        "temporal_coverage does not reproduce the PROFILE (the config-echo/projection "
        "defect the equality exists to catch):\n  " + "\n  ".join(grain_mismatches)
    )


@pytest.mark.llm
def test_absence_falls_loud_null_contract(strategy_name: str) -> None:
    """Irregular/unknown grain OR unprofiled ⇒ NULL completeness fields — never a
    synthesized 0 / 1.0 / True."""
    with workspace_session() as session:
        if not read_view_exists(session, "og_temporal_coverage"):
            pytest.skip("og_temporal_coverage absent — pre-cutover engine")
        read_schema = _read_schema(session)
        edges = _coverage_edges(session, read_schema)

    if not edges:
        pytest.skip("no temporal_coverage edges on this corpus")

    violations: list[str] = []
    for e in edges:
        if e.observed_grain in _GRAINED:
            continue  # a regular grain may legitimately carry completeness numbers
        for field in ("completeness_ratio", "expected_periods", "actual_periods",
                      "last_period_complete"):
            value = getattr(e, field)
            if value is not None:
                violations.append(
                    f"{e.table_name}.{e.column_name} (grain={e.observed_grain!r}): "
                    f"{field}={value!r} — must be NULL (absence falls loud, never synthesized)"
                )
    n_ungrained = sum(1 for e in edges if e.observed_grain not in _GRAINED)
    print(f"\n[null contract] {n_ungrained}/{len(edges)} edges carry no regular grain")
    assert not violations, "\n  ".join(["completeness synthesized where the grain is absent:"] + violations)


@pytest.mark.llm
def test_anchor_one_home(strategy_name: str) -> None:
    """og_columns.anchor_time_axis, PER COLUMN: a measure whose lineage witness
    reconciled carries the witness's axis; every other column carries its OWN
    table's single declared is_anchor event column — never positional.

    (v1 of this test compared every column against a table-level expectation and
    misapplied the witness's EVENT-table axis to the measure's table — the sweep-#1
    reds it produced were this oracle's bug, not the engine's.)
    """
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, "og_columns"):
            pytest.skip("og_columns absent — pre-cutover engine")
        read_schema = _read_schema(session)
        declared = _declared_time_columns(session, read_schema)
        anchors = session.execute(
            text(
                "SELECT t.table_name AS table_name, c.column_name AS column_name, "
                "c.column_id AS column_id, c.anchor_time_axis AS anchor_time_axis "
                f'FROM "{read_schema}".og_columns c '
                "JOIN tables t ON t.table_id = c.table_id "
                "WHERE c.anchor_time_axis IS NOT NULL"
            )
        ).all()
        witness = session.execute(
            text(
                "SELECT mal.measure_column_id AS column_id, "
                "mal.event_time_axis_column AS axis "
                f'FROM "{read_schema}".current_measure_aggregation_lineage mal '
                "WHERE mal.event_time_axis_column IS NOT NULL"
            )
        ).all()

    if not anchors:
        pytest.skip("no anchor_time_axis populated on this corpus")

    witness_by_column = {r.column_id: r.axis for r in witness}
    declared_anchor_by_table: dict[str, str] = {}
    for table, cols in declared.items():
        event_anchors = [
            c["column"] for c in cols if c.get("role") == "event" and c.get("is_anchor")
        ]
        if len(event_anchors) == 1:
            declared_anchor_by_table[table] = event_anchors[0]

    problems: list[str] = []
    checked = 0
    for r in anchors:
        expected = witness_by_column.get(r.column_id) or declared_anchor_by_table.get(
            r.table_name
        )
        if expected is None:
            continue  # no one-home basis for this column — nothing to hold it to
        checked += 1
        if r.anchor_time_axis != expected:
            home = "witness" if r.column_id in witness_by_column else "declared"
            problems.append(
                f"{r.table_name}.{r.column_name}: anchor={r.anchor_time_axis!r}, "
                f"one-home ({home}) says {expected!r}"
            )
    print(f"\n[anchor one-home] {checked}/{len(anchors)} anchored columns checked, "
          f"{len(problems)} divergent")
    assert not problems, (
        "anchor_time_axis diverges from its one home (witness ▸ declared):\n  "
        + "\n  ".join(problems)
    )


@pytest.mark.llm
def test_period_ladder_and_rollup(strategy_name: str) -> None:
    """The period ladder is exactly day→month→quarter→year (ascending ordinals);
    drilldown hierarchies project rolls_up_to finer→coarser; alias/role emit none."""
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, "og_period_rolls_up_to"):
            pytest.skip("og_period_rolls_up_to absent — pre-cutover engine")
        read_schema = _read_schema(session)
        graph = f'"{read_schema}".operating_model'
        ladder = session.execute(
            text(
                f"SELECT * FROM GRAPH_TABLE ({graph} "
                "MATCH (a IS period_grain)-[r IS period_rolls_up_to]->(b IS period_grain) "
                "COLUMNS (a.grain AS from_grain, a.ordinal AS from_ordinal, "
                "b.grain AS to_grain, b.ordinal AS to_ordinal))"
            )
        ).all()
        hierarchy_kinds = session.execute(
            text(
                "SELECT hierarchy_id, kind FROM "
                f'"{read_schema}".current_dimension_hierarchies'
            )
        ).all()
        rollups = session.execute(
            text(
                f"SELECT * FROM GRAPH_TABLE ({graph} "
                "MATCH (a IS column_node)-[r IS rolls_up_to]->(b IS column_node) "
                "COLUMNS (r.hierarchy_id AS hierarchy_id, r.from_level AS from_level, "
                "r.to_level AS to_level))"
            )
        ).all()

    got_ladder = {(r.from_grain, r.to_grain) for r in ladder}
    assert got_ladder == {("day", "month"), ("month", "quarter"), ("quarter", "year")}, (
        f"period ladder is {sorted(got_ladder)} — must be exactly day→month→quarter→year"
    )
    assert all(r.from_ordinal < r.to_ordinal for r in ladder), "ladder ordinals not ascending"

    drilldown = {str(r.hierarchy_id) for r in hierarchy_kinds if r.kind == "drilldown"}
    non_drill = {str(r.hierarchy_id) for r in hierarchy_kinds if r.kind != "drilldown"}
    bad_level = [r for r in rollups if r.to_level != r.from_level - 1]
    leaked = [r for r in rollups if str(r.hierarchy_id) in non_drill]
    print(
        f"\n[roll-up] ladder ✓; {len(rollups)} rolls_up_to edges over "
        f"{len(drilldown)} drilldown hierarchies ({len(non_drill)} alias/role emit none)"
    )
    assert not bad_level, (
        "rolls_up_to edges not finer→coarser (level n → n-1): "
        + ", ".join(f"h={r.hierarchy_id} {r.from_level}→{r.to_level}" for r in bad_level)
    )
    assert not leaked, (
        f"alias/role hierarchies leaked rolls_up_to edges: {sorted({str(r.hierarchy_id) for r in leaked})}"
    )


@pytest.mark.llm
def test_calendar_stamped_never_silent(strategy_name: str) -> None:
    """Unset workspace ⇒ fiscal_year_start_month=1 + calendar_source='default';
    declared ⇒ the declaration + 'declared'. Every grain row is stamped."""
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, "og_period_grain"):
            pytest.skip("og_period_grain absent — pre-cutover engine")
        read_schema = _read_schema(session)
        grains = session.execute(
            text(
                "SELECT grain, fiscal_year_start_month, calendar_source "
                f'FROM "{read_schema}".og_period_grain'
            )
        ).all()
        declared = session.execute(
            text("SELECT fiscal_year_start_month FROM workspace_calendar")
        ).all()

    assert grains, "og_period_grain is EMPTY — the calendar substrate must always exist"
    declared_month = declared[0].fiscal_year_start_month if declared else None
    problems: list[str] = []
    for g in grains:
        if declared_month is not None:
            ok = g.fiscal_year_start_month == declared_month and g.calendar_source == "declared"
        else:
            ok = g.fiscal_year_start_month == 1 and g.calendar_source == "default"
        if not ok:
            problems.append(
                f"{g.grain}: month={g.fiscal_year_start_month} source={g.calendar_source!r}"
            )
    mode = f"declared={declared_month}" if declared_month is not None else "default"
    print(f"\n[calendar] {len(grains)} grain rows stamped ({mode})")
    assert not problems, (
        "calendar not stamped visibly (unset must read default/1, declared must follow "
        "the declaration):\n  " + "\n  ".join(problems)
    )
