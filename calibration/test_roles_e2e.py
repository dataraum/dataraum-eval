"""Table + column role accuracy vs metadata_truth.yaml (DAT-680 P1, DAT-685).

Grades the agent's role/semantic surfaces against ground truth authored from the
generator STRUCTURE (not detector output):

* ``current_table_entities`` — is_fact_table (HARD where structure decides it),
  ``detected_entity_type`` (reported: free text, no ontology vocabulary to grade).
* ``current_semantic_annotations`` — semantic_role. measure + timestamp are HARD
  (load-bearing: drivers_phase filters ``semantic_role='measure'``, slicing reads
  timestamps); key/dimension/attribute are reported (convention-dependent).
* ``current_column_concepts`` — business_concept. The measure→ontology-concept
  bindings metric grounding depends on are HARD; dimension bindings are reported.

The determinism split is the DAT-685 rule: HARD only where structurally
unambiguous, everything else reported — never a truth patch, never a deterministic
override of an LLM judgment. Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import (
    load_truth,
    read_business_concepts,
    read_semantic_roles,
    read_table_entities,
)
from calibration.tools._runs import workspace_session

_STRATEGY = "clean"


def _activate_or_skip() -> None:
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {_STRATEGY!r}; run "
            f"`python -m calibration.run -s {_STRATEGY}` first"
        )
    runner_mod.activate_workspace(_STRATEGY)


@pytest.mark.llm
def test_fact_dimension_roles() -> None:
    """Fact/dimension classification is right where structure decides it (HARD).

    Measure-bearing transaction/snapshot tables are facts; a pure reference table is
    a dimension. journal_entries (event header, no measure) and fx_rates (a rate
    lookup) are structurally debatable — reported, not asserted. entity_type is free
    text with no ontology vocabulary — reported for review only.
    """
    _activate_or_skip()
    with workspace_session() as session:
        entities = read_table_entities(session)

    roles = load_truth().get("table_roles") or {}
    facts = set(roles.get("facts") or [])
    dims = set(roles.get("dimensions") or [])
    ambiguous = set(roles.get("ambiguous") or [])

    print("\n[table roles] detected classification (entity_type reported):")
    for tbl in sorted(entities):
        e = entities[tbl]
        tag = "fact" if tbl in facts else "dim" if tbl in dims else "ambiguous" if tbl in ambiguous else "?"
        print(f"  {tbl:<22} is_fact={e['is_fact']!s:<5} is_dim={e['is_dimension']!s:<5} "
              f"entity={e['entity_type']!r}  [{tag}]")

    wrong: list[str] = []
    for tbl in sorted(facts):
        e = entities.get(tbl)
        if e is None:
            wrong.append(f"  {tbl}: expected FACT, absent from table_entities")
        elif not e["is_fact"]:
            wrong.append(f"  {tbl}: expected FACT, got is_fact={e['is_fact']} is_dim={e['is_dimension']}")
    for tbl in sorted(dims):
        e = entities.get(tbl)
        if e is None:
            wrong.append(f"  {tbl}: expected DIMENSION, absent from table_entities")
        elif e["is_fact"] or not e["is_dimension"]:
            wrong.append(f"  {tbl}: expected DIMENSION, got is_fact={e['is_fact']} is_dim={e['is_dimension']}")

    assert not wrong, (
        "fact/dimension classification is wrong where structure is unambiguous "
        "(measure-bearing = fact, pure reference = dimension):\n" + "\n".join(wrong)
    )


@pytest.mark.llm
def test_measure_role_recall_and_precision() -> None:
    """Exactly the true measure columns carry semantic_role='measure' (HARD).

    Load-bearing: drivers_phase and the additivity classifier consume
    ``semantic_role='measure'``. A true measure mislabeled is silently dropped from
    both; a non-measure mislabeled measure pollutes them. So both directions are hard.
    """
    _activate_or_skip()
    with workspace_session() as session:
        roles = read_semantic_roles(session)

    expected = set(load_truth().get("semantic_roles", {}).get("measure") or [])
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
def test_timestamp_role_recall() -> None:
    """Every genuine date column carries semantic_role='timestamp' (HARD).

    Slicing reads timestamp columns as its time axes; a date mislabeled is dropped
    from temporal analysis. Also prints the key/dimension/attribute assignments for
    review — those are convention-dependent and reported, not asserted.
    """
    _activate_or_skip()
    with workspace_session() as session:
        roles = read_semantic_roles(session)

    expected = set(load_truth().get("semantic_roles", {}).get("timestamp") or [])
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
def test_business_concept_grounding() -> None:
    """The measure→ontology-concept bindings metric grounding needs are present (HARD).

    A missing binding means the metric cannot ground its measure. Dimension-concept
    bindings (account/currency/fiscal_period/entity) are LLM-selective discriminators
    — printed for review, not required.
    """
    _activate_or_skip()
    with workspace_session() as session:
        concepts = read_business_concepts(session)

    required: dict[str, str] = load_truth().get("business_concepts", {}).get("required") or {}
    assert required, "no required business_concept bindings declared"

    wrong: list[str] = []
    for col, want in sorted(required.items()):
        got = concepts.get(col)
        marker = "✓" if got == want else "✗"
        print(f"  {marker} {col}: {got!r} (need {want!r})")
        if got != want:
            wrong.append(f"  {col}: bound {got!r}, need {want!r}")

    extra = {c: b for c, b in sorted(concepts.items()) if c not in required}
    print("[business_concept — reported (dimension bindings, not required)]:")
    for c, b in extra.items():
        print(f"  {c} -> {b}")

    assert not wrong, (
        "a measure→ontology-concept binding metric grounding depends on is wrong or "
        "missing:\n" + "\n".join(wrong)
    )
