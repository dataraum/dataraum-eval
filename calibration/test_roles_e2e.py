"""Table + column role accuracy vs metadata_truth.yaml (DAT-680 P1, DAT-685).

Grades the agent's role/semantic surfaces against ground truth authored from the
generator STRUCTURE (not detector output):

* ``current_table_entities`` — ``table_role`` (DAT-728: fact | periodic_snapshot |
  dimension; HARD where structure decides it), ``detected_entity_type`` (reported:
  free text, no ontology vocabulary to grade).
* ``current_semantic_annotations`` — semantic_role. measure + timestamp are HARD
  (load-bearing: drivers_phase filters ``semantic_role='measure'``, slicing reads
  timestamps); key/dimension/attribute are reported (convention-dependent).
* ``current_column_concepts`` — meaning presence (DAT-769). The measure→ontology-concept
  bindings metric grounding depends on are HARD; dimension bindings are reported.

The determinism split is the DAT-685 rule: HARD only where structurally
unambiguous, everything else reported — never a truth patch, never a deterministic
override of an LLM judgment. Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import (
    is_wild,
    read_column_meanings,
    read_semantic_roles,
    read_table_entities,
)
from calibration.tools._runs import workspace_session


@pytest.fixture(autouse=True)
def _scoped_run(strategy_name: str) -> None:
    """Grade ONLY the strategy under test against its own truth (DAT-797)."""
    require_pipeline_run(strategy_name)


@pytest.mark.llm
def test_fact_dimension_roles(metadata_truth: dict[str, Any]) -> None:
    """Fact/dimension classification is right where structure decides it (HARD).

    Measure-bearing transaction/snapshot tables are facts; a pure reference table is
    a dimension. journal_entries (event header, no measure) and fx_rates (a rate
    lookup) are structurally debatable — reported, not asserted. entity_type is free
    text with no ontology vocabulary — reported for review only.
    """
    with workspace_session() as session:
        entities = read_table_entities(session)

    roles = metadata_truth.get("table_roles") or {}
    facts = set(roles.get("facts") or [])
    dims = set(roles.get("dimensions") or [])
    ambiguous = set(roles.get("ambiguous") or [])

    print("\n[table roles] detected classification (entity_type reported):")
    for tbl in sorted(entities):
        e = entities[tbl]
        tag = "fact" if tbl in facts else "dim" if tbl in dims else "ambiguous" if tbl in ambiguous else "?"
        print(f"  {tbl:<22} role={e['role']!s:<18} entity={e['entity_type']!r}  [{tag}]")

    wrong: list[str] = []
    for tbl in sorted(facts):
        ent = entities.get(tbl)
        if ent is None:
            wrong.append(f"  {tbl}: expected FACT, absent from table_entities")
        elif not ent["is_fact"]:
            wrong.append(f"  {tbl}: expected FACT, got table_role={ent['role']!r}")
    for tbl in sorted(dims):
        ent = entities.get(tbl)
        if ent is None:
            wrong.append(f"  {tbl}: expected DIMENSION, absent from table_entities")
        elif ent["is_fact"] or not ent["is_dimension"]:
            wrong.append(f"  {tbl}: expected DIMENSION, got table_role={ent['role']!r}")

    assert not wrong, (
        "fact/dimension classification is wrong where structure is unambiguous "
        "(measure-bearing = fact, pure reference = dimension):\n" + "\n".join(wrong)
    )


@pytest.mark.llm
def test_measure_role_recall_and_precision(metadata_truth: dict[str, Any]) -> None:
    """Exactly the true measure columns carry semantic_role='measure' (HARD).

    Load-bearing: drivers_phase and the additivity classifier consume
    ``semantic_role='measure'``. A true measure mislabeled is silently dropped from
    both; a non-measure mislabeled measure pollutes them. So both directions are hard.
    """
    with workspace_session() as session:
        roles = read_semantic_roles(session)

    expected = set(metadata_truth.get("semantic_roles", {}).get("measure") or [])
    if not expected and is_wild(metadata_truth):
        pytest.skip("Tier-B corpus declares no measure roles — structural truth only")
    assert expected, "no measure ground truth declared"
    actual = {col for col, r in roles.items() if r == "measure"}

    missing = sorted(c for c in expected if roles.get(c) != "measure")   # recall
    spurious = sorted(actual - expected)                                 # precision
    print(f"\n[measure role] recall {len(expected) - len(missing)}/{len(expected)}, "
          f"{len(spurious)} spurious")
    for c in missing:
        print(f"  MISSING: {c} is {roles.get(c, '<unannotated>')!r}, expected measure")
    for c in spurious:
        print(f"  SPURIOUS: {c} labeled measure, not a true measure")

    assert not missing and not spurious, (
        "semantic_role='measure' does not match the true measure set — a mislabel "
        "silently drops or pollutes the driver + additivity input:\n  "
        + "\n  ".join(f"MISSING {c}" for c in missing)
        + ("\n  " if missing and spurious else "")
        + "\n  ".join(f"SPURIOUS {c}" for c in spurious)
    )


@pytest.mark.llm
def test_timestamp_role_recall(metadata_truth: dict[str, Any]) -> None:
    """Every genuine date column carries semantic_role='timestamp' (HARD).

    Slicing reads timestamp columns as its time axes; a date mislabeled is dropped
    from temporal analysis. Also prints the key/dimension/attribute assignments for
    review — those are convention-dependent and reported, not asserted.
    """
    with workspace_session() as session:
        roles = read_semantic_roles(session)

    expected = set(metadata_truth.get("semantic_roles", {}).get("timestamp") or [])
    assert expected, "no timestamp ground truth declared"

    missing = sorted(c for c in expected if roles.get(c) != "timestamp")
    print(f"\n[timestamp role] recall {len(expected) - len(missing)}/{len(expected)}")
    for c in missing:
        print(f"  MISSING: {c} is {roles.get(c, '<unannotated>')!r}, expected timestamp")

    graded = set(expected)
    reported = {c: r for c, r in sorted(roles.items())
                if c not in graded and r in {"key", "dimension", "attribute"}}
    print("[semantic role — reported (key/dimension/attribute, not asserted)]:")
    for c, r in reported.items():
        print(f"  {c}: {r}")

    assert not missing, (
        "genuine date column(s) not labeled timestamp — dropped from slicing time "
        "axes:\n  " + "\n  ".join(missing)
    )


@pytest.mark.llm
def test_column_meanings_present(metadata_truth: dict[str, Any]) -> None:
    """Every column metric grounding depends on carries an authored meaning (DAT-769).

    The exact-binding oracle is RETIRED — meanings are graded at the CONSUMERS
    (cycle recall, reconciliation coverage, /deliver accuracy), never as strings
    against a fixed truth. This smoke pins the presence contract only; the
    printout is for human inspection of grounding-context quality.
    """
    with workspace_session() as session:
        meanings = read_column_meanings(session)

    required_cols = metadata_truth.get("business_concepts", {}).get("required") or {}
    print(f"\n[column meanings] {len(meanings)} columns carry a meaning")
    for c, m in sorted(meanings.items()):
        print(f"  {c}: {m[:110]}")

    assert meanings, "no column carries a meaning — the grounding context is empty"
    missing = [c for c in required_cols if c not in meanings]
    assert not missing, (
        "columns metric grounding depends on carry no meaning:\n"
        + "\n".join(f"  {c}" for c in missing)
    )
