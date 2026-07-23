"""Generated validations — the O5 induction oracle (P10/DAT-735).

Grades the ``validation_induction`` phase's output in the ``validations`` home:

1. **Induction liveness (HARD on finance)** — the OM run generates >= 1
   ``source='generated'`` validation on the finance corpus (a rich promoted graph
   yields grounded proposals). Accepted engine limitation, graded accordingly: the
   FIRST OM run serves the PRIOR run's cycles/additivity (empty on run 1), so
   induction proposes from the structural substrate + metric DAG alone — this
   oracle never demands cycle-informed checks on a first run, only liveness.
2. **No fabricated grounding (HARD, defense-in-depth)** — every generated row was
   EXECUTED (a validation_results row exists for it): the engine
   membership-validates at induction; a generated validation that never binds is
   exactly the fabrication this read exists to catch.
3. **Declared/generated separation (HARD)** — ``source`` ∈ {seed, generated,
   NULL} exactly, and the finance corpus's declared (seed) set is present —
   induction can never flip ``nothing_declared`` because generated ≠ declared
   (pinned engine-side; the zero-declare corpus that proves the flip-impossibility
   end-to-end is band 6's exam, not this corpus's).
4. **check_type vocabulary (HARD)** — every persisted validation row's
   ``check_type`` ∈ {aggregate, balance, comparison, constraint} — the
   cross-package contract read (mirrors the cockpit zod contract; the engine CHECK
   enforces it, this is the defense-in-depth read).

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import is_wild
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")

_CHECK_TYPES = frozenset({"aggregate", "balance", "comparison", "constraint"})


@pytest.fixture(autouse=True)
def _completed_run(strategy_name: str) -> None:
    require_pipeline_run(strategy_name)


def _validations(session: Any) -> list[Any]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT validation_id, name, source, check_type, severity, category "
            "FROM validations WHERE superseded_at IS NULL"
        )
    ).all()
    return list(rows)


@pytest.mark.llm
def test_induction_liveness(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """>= 1 generated validation on the finance corpus (liveness, not volume)."""
    with workspace_session() as session:
        rows = _validations(session)

    if is_wild(metadata_truth):
        pytest.skip("Tier-B corpus — induction liveness is graded on the declaring vertical")
    if not rows:
        pytest.skip(
            "validations home empty — the operating_model workflow (validation_induction "
            "phase) did not run this pass"
        )
    generated = [r for r in rows if r.source == "generated"]
    print(f"\n[induction] {len(generated)} generated / {len(rows)} total validations")
    assert generated, (
        "validation_induction produced ZERO generated validations on the finance corpus — "
        "a rich promoted graph (structural substrate + metric DAG, run-1 scope) should "
        "yield grounded proposals; absence falls loud"
    )


@pytest.mark.llm
def test_no_fabricated_grounding(strategy_name: str) -> None:
    """Every generated validation was executed — a generated row with no
    validation_results row never bound (the fabrication this read catches)."""
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    with workspace_session() as session:
        rows = _validations(session)
        generated = [r for r in rows if r.source == "generated"]
        if not generated:
            pytest.skip("no generated validations this run — liveness is its own oracle")
        read_schema = read_schema_name_for(
            str(session.execute(text("SELECT current_schema()")).scalar())
        )
        executed = {
            r.validation_id
            for r in session.execute(
                text(f'SELECT DISTINCT validation_id FROM "{read_schema}".current_validation_results')
            ).all()
        }

    unbound = sorted({r.validation_id for r in generated} - executed)
    print(f"\n[no fabrication] {len(generated)} generated, {len(unbound)} never executed")
    assert not unbound, (
        "generated validation(s) never produced a validation_results row — proposed but "
        "never bound/executed (membership validation's defense-in-depth read):\n  "
        + "\n  ".join(unbound)
    )


@pytest.mark.llm
def test_declared_generated_separation(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """source vocabulary exact; the declaring vertical's seed set present."""
    with workspace_session() as session:
        rows = _validations(session)

    if not rows:
        pytest.skip("validations home empty this pass")
    bad_source = [r.validation_id for r in rows if r.source not in ("seed", "generated", None)]
    assert not bad_source, f"unknown validation source values (generated ≠ declared): {bad_source}"
    if is_wild(metadata_truth):
        return
    seeds = [r for r in rows if r.source == "seed"]
    print(f"\n[separation] {len(seeds)} seed (declared) / "
          f"{sum(1 for r in rows if r.source == 'generated')} generated")
    assert seeds, (
        "the finance corpus declares seed validations but NONE are present — the "
        "declared home is empty (this is what would wrongly flip nothing_declared)"
    )


@pytest.mark.llm
def test_check_type_vocabulary(strategy_name: str) -> None:
    """Every persisted validation's check_type ∈ the four-value contract."""
    with workspace_session() as session:
        rows = _validations(session)

    if not rows:
        pytest.skip("validations home empty this pass")
    bad = [f"{r.validation_id}: {r.check_type!r}" for r in rows if r.check_type not in _CHECK_TYPES]
    print(f"\n[check_type] {len(rows)} rows, {len(bad)} outside the contract")
    assert not bad, (
        "check_type outside the four-value cross-package contract "
        "(aggregate|balance|comparison|constraint):\n  " + "\n  ".join(bad)
    )
