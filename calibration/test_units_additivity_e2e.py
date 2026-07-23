"""Units & additivity projection — the O2 graph oracle (P6/DAT-731).

Grades the promoted graph's unit surface against the generator's ``measured_in``
truth (CAP-measured-in-truth: authored from the models, ``cross_unit``
data-derived at export):

1. **measured_in coverage (HARD, label-invariant)** — every truth pairing
   (measure → same-table unit column) carries an ``og_measured_in`` edge to that
   unit column. **Skip (not vacuous-pass) when zero edges exist** — grounding
   recall is /smoke's concern, mirroring test_metric_additivity_e2e's skip
   discipline. A ``dimensionless`` truth entry (fx_rates.rate — a currency-pair
   ratio) must project NO edge. A null-unit non-dimensionless entry (the balance
   facts at canonical, denominated via the account FK) is REPORTED if the engine
   resolves a cross-table pointer — richer than our structural truth, not a
   failure.
2. **og_additivity parity (HARD, plumbing only)** — the ``additivity_verdict``
   vertex reproduces ``current_metric_additivity`` row-for-row; verdict VALUES
   are already graded by test_metric_additivity_e2e and are NOT re-graded here.
3. **Cross-unit gate surface (HARD)** — the drill unit gate (cockpit DAT-731)
   flags a measure iff its unit column's distinct count exceeds 1; the
   engine-side surface it consumes is the typed statistical profile. Assert
   ``(distinct_count > 1) == cross_unit`` truth per (fact, column): silent
   everywhere on a single-currency corpus, flagged set == truth on a
   mixed-currency variant (the declared mix_units path).
4. **No self-denominated fabrication (HARD)** — this corpus defines no
   self-denominated measure; a ``self_denominated`` edge is a finding.

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import read_view_exists
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    require_pipeline_run(strategy_name)


def _read_schema(session: Any) -> str:
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    return read_schema_name_for(str(session.execute(text("SELECT current_schema()")).scalar()))


def _truth_entries(metadata_truth: dict[str, Any]) -> list[dict[str, Any]]:
    return list(metadata_truth.get("measured_in") or [])


def _measured_in_edges(session: Any, read_schema: str) -> list[Any]:
    from sqlalchemy import text

    graph = f'"{read_schema}".operating_model'
    rows = session.execute(
        text(
            f"SELECT * FROM GRAPH_TABLE ({graph} "
            "MATCH (m IS column_node)-[u IS measured_in]->(unit IS column_node) "
            "COLUMNS (m.table_id AS table_id, m.column_name AS measure_column, "
            "unit.column_name AS unit_column, unit.table_id AS unit_table_id, "
            "u.self_denominated AS self_denominated))"
        )
    ).all()
    return list(rows)


def _table_names(session: Any) -> dict[str, str]:
    from sqlalchemy import text

    from calibration.tools._runs import short

    rows = session.execute(text("SELECT table_id, table_name FROM tables")).all()
    return {r.table_id: short(r.table_name) for r in rows}


@pytest.mark.llm
def test_measured_in_coverage(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """Every truth (measure → unit column) pairing carries the og_measured_in edge."""
    truth = _truth_entries(metadata_truth)
    if not truth:
        pytest.skip("no measured_in ground truth for this corpus (Tier-B declares none)")

    with workspace_session() as session:
        if not read_view_exists(session, "og_measured_in"):
            pytest.skip("og_measured_in element view absent — pre-cutover engine")
        read_schema = _read_schema(session)
        edges = _measured_in_edges(session, read_schema)
        names = _table_names(session)

    if not edges:
        pytest.skip(
            "no measured_in edges projected this run — unit-source authoring recall "
            "is /smoke's concern (skip-not-vacuous, the metric_additivity discipline)"
        )

    got = {
        (f"{names.get(e.table_id, '?')}.{e.measure_column}",
         f"{names.get(e.unit_table_id, '?')}.{e.unit_column}")
        for e in edges
    }
    got_by_measure: dict[str, set[str]] = {}
    for measure, unit in got:
        got_by_measure.setdefault(measure, set()).add(unit)

    missing: list[str] = []
    fabricated_dimensionless: list[str] = []
    for entry in truth:
        measure, unit = entry["measure"], entry["unit_column"]
        if entry.get("dimensionless"):
            if measure in got_by_measure:
                fabricated_dimensionless.append(
                    f"{measure} is dimensionless but projects {sorted(got_by_measure[measure])}"
                )
            continue
        if unit is None:
            if measure in got_by_measure:  # cross-table resolution — richer than truth
                print(f"  [info] {measure}: engine resolved {sorted(got_by_measure[measure])} "
                      "(no same-table unit source in truth)")
            continue
        if unit not in got_by_measure.get(measure, set()):
            missing.append(f"{measure} → {unit} (edge absent)")

    covered = sum(
        1 for e in truth
        if e["unit_column"] and e["unit_column"] in got_by_measure.get(e["measure"], set())
    )
    total = sum(1 for e in truth if e["unit_column"])
    print(f"\n[measured_in] {covered}/{total} truth pairings projected; {len(got)} edges total")
    assert not fabricated_dimensionless, (
        "dimensionless measures must project NO measured_in edge:\n  "
        + "\n  ".join(fabricated_dimensionless)
    )
    assert not missing, (
        "generator-truth unit pairings missing from og_measured_in:\n  " + "\n  ".join(missing)
    )


@pytest.mark.llm
def test_additivity_parity(strategy_name: str) -> None:
    """The additivity_verdict vertex reproduces current_metric_additivity row-for-row
    (plumbing; the verdict VALUES are test_metric_additivity_e2e's job)."""
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, "og_additivity"):
            pytest.skip("og_additivity element view absent — pre-cutover engine")
        read_schema = _read_schema(session)
        graph = f'"{read_schema}".operating_model'
        vertex = session.execute(
            text(
                f"SELECT * FROM GRAPH_TABLE ({graph} "
                "MATCH (a IS additivity_verdict) "
                "COLUMNS (a.target_kind AS target_kind, a.target_key AS target_key))"
            )
        ).all()
        view = session.execute(
            text(
                "SELECT target_kind, target_key "
                f'FROM "{read_schema}".current_metric_additivity'
            )
        ).all()

    if not view:
        pytest.skip("current_metric_additivity is empty this run (graded by its own oracle)")

    vertex_keys = {(r.target_kind, r.target_key) for r in vertex}
    view_keys = {(r.target_kind, r.target_key) for r in view}
    print(f"\n[additivity parity] vertex={len(vertex)} view={len(view)}")
    assert vertex_keys == view_keys and len(vertex) == len(view), (
        "og_additivity does not reproduce current_metric_additivity row-for-row: "
        f"vertex-only={sorted(vertex_keys - view_keys)}, view-only={sorted(view_keys - vertex_keys)}"
    )


@pytest.mark.llm
def test_cross_unit_gate_surface(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """(distinct_count > 1) on the unit column == the data-derived cross_unit truth,
    per (fact, column) — the exact surface the drill unit gate consumes."""
    from sqlalchemy import text

    truth = [e for e in _truth_entries(metadata_truth) if e["unit_column"]]
    if not truth:
        pytest.skip("no unit-columned measured_in truth for this corpus")

    with workspace_session() as session:
        read_schema = _read_schema(session)
        rows = session.execute(
            text(
                "SELECT t.table_name AS table_name, c.column_name AS column_name, "
                "p.distinct_count AS distinct_count "
                f'FROM "{read_schema}".current_statistical_profiles p '
                "JOIN columns c ON c.column_id = p.column_id "
                "JOIN tables t ON t.table_id = c.table_id "
                "WHERE p.layer = 'typed'"
            )
        ).all()

    from calibration.tools._runs import short

    distinct = {(short(r.table_name), r.column_name): r.distinct_count for r in rows}
    mismatches: list[str] = []
    checked = 0
    for entry in truth:
        table, _, col = str(entry["unit_column"]).partition(".")
        dc = distinct.get((table, col))
        if dc is None:
            continue  # unit column unprofiled — nothing for the gate to read
        checked += 1
        actual_cross = dc > 1
        if actual_cross != bool(entry["cross_unit"]):
            mismatches.append(
                f"{entry['measure']}: unit {entry['unit_column']} distinct_count={dc} "
                f"(gate {'flags' if actual_cross else 'silent'}) but truth cross_unit="
                f"{entry['cross_unit']}"
            )
    print(f"\n[cross-unit surface] {checked}/{len(truth)} unit columns profiled and checked")
    if not checked:
        pytest.skip("no unit column carries a typed statistical profile this run")
    assert not mismatches, (
        "the gate's surface disagrees with the data-derived cross_unit truth "
        "(per-(fact, column) — a sibling fact must never mask):\n  " + "\n  ".join(mismatches)
    )


@pytest.mark.llm
def test_no_self_denominated_fabrication(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """This corpus defines no self-denominated measure — a self-loop is a finding."""
    truth = _truth_entries(metadata_truth)
    if not truth:
        pytest.skip("no measured_in ground truth for this corpus (Tier-B declares none)")

    with workspace_session() as session:
        if not read_view_exists(session, "og_measured_in"):
            pytest.skip("og_measured_in element view absent — pre-cutover engine")
        edges = _measured_in_edges(session, _read_schema(session))

    self_denominated = [e for e in edges if e.self_denominated]
    assert not self_denominated, (
        "self_denominated measured_in edges on a corpus that defines none: "
        + ", ".join(f"{e.measure_column}" for e in self_denominated)
    )
