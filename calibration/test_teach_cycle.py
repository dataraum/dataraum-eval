"""Teach-closure (DAT-447 scenario 6) — the framework's core claim, end to end.

ADR-0009's whole thesis is that a *taught answer drops the disagreement*. This runs
detection-null-v1, teaches the injected sentinels as null markers, RE-RUNS the same
session, and asserts the pooled conflict ``C`` on the taught column collapses.

The drop is only OBSERVABLE because scores are read head-resolved (conftest Step-0,
``_head_resolved_entropy_rows``): a raw ``max()`` over the pre- and post-teach runs'
coexisting rows would surface the stale high C and hide the closure.

Tier-3 (docker + Temporal + LLM): marked ``llm``. Uses ``bank_transactions.amount``
— the dense column that types robustly — to isolate teach-closure from the
borderline-typing flake on journal_lines.debit (project_typing_nondeterminism).
"""

from __future__ import annotations

import pytest
import yaml
from dataraum.core.connections import ConnectionConfig, ConnectionManager
from dataraum.storage.read_views import read_schema_name_for
from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.conftest import DATA_DIR

_STRATEGY = "detection-null-v1"
_TABLE, _COLUMN = "bank_transactions", "amount"
_DROP_MARGIN = 0.02  # anti-noise floor on the signed delta, NOT a point threshold

_UNIT_STRATEGY = "detection-unit-v1"
_UNIT_TABLE, _UNIT_COLUMN, _TAUGHT_UNIT = "bank_transactions", "amount", "EUR"

_TB_STRATEGY = "detection-v1"
_TB_TABLE, _TB_COLUMN = "trial_balance", "debit_balance"
_TB_CONCEPT = "account_balance"  # the concept debit_balance binds to (point_in_time prior)


def _null_semantics_conflict(session_id: str, table_substr: str, column: str) -> float | None:
    """Head-resolved pooled conflict C for a column's null_semantics object."""
    runner_mod.bootstrap_engine()  # PG/Temporal env + workspace schema (idempotent)
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            read_schema = read_schema_name_for(
                str(s.execute(text("SELECT current_schema()")).scalar())
            )
            rows = s.execute(
                text(
                    f'SELECT target, score FROM "{read_schema}".current_entropy_objects '
                    "WHERE session_id = :sid AND detector_id = 'null_semantics'"
                ),
                {"sid": session_id},
            ).all()
    finally:
        mgr.close()
    for r in rows:
        if table_substr in r.target and r.target.endswith("." + column):
            return float(r.score)
    return None


@pytest.mark.llm
def test_teach_null_value_drops_adjudication_conflict() -> None:
    """A null_value teach on the injected sentinels collapses the column's conflict C."""
    if not (DATA_DIR / _STRATEGY).exists():
        pytest.skip(
            f"no data for {_STRATEGY}; run `python -m calibration.runner {_STRATEGY}` first"
        )

    sidecar = runner_mod.sidecar_path(_STRATEGY)
    run = (
        runner_mod.CalibrationRun.from_json(sidecar.read_text())
        if sidecar.exists()
        else runner_mod.run_pipeline(_STRATEGY)
    )

    before = _null_semantics_conflict(run.session_id, _TABLE, _COLUMN)
    if before is None:
        pytest.skip(f"null_semantics did not fire on {_TABLE}.{_COLUMN} in the baseline run")

    emap = yaml.safe_load((DATA_DIR / _STRATEGY / "entropy_map.yaml").read_text())
    markers = next(
        inj["parameters"]["markers"]
        for inj in emap["injections"]
        if inj["target_column"] == _COLUMN and _TABLE in inj["target_file"]
    )

    runner_mod.teach_null_value_and_rerun(run, values=markers)

    after = _null_semantics_conflict(run.session_id, _TABLE, _COLUMN)
    assert after is not None, "null_semantics object vanished after the teach re-run"
    # Teach-closure: the taught vocabulary makes the vocabulary witness agree, so the
    # pooled conflict drops. Signed-delta grammar (ADR-0009), never a point threshold.
    assert after < before - _DROP_MARGIN, (
        f"teach did not close the conflict: C {before:.3f} -> {after:.3f} "
        f"(delta {after - before:+.3f}, expected drop > {_DROP_MARGIN})"
    )


def _temporal_behavior_conflict(session_id: str, table_substr: str, column: str) -> float | None:
    """Head-resolved pooled conflict C for a column's temporal_behavior object."""
    runner_mod.bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            read_schema = read_schema_name_for(
                str(s.execute(text("SELECT current_schema()")).scalar())
            )
            rows = s.execute(
                text(
                    f'SELECT target, score FROM "{read_schema}".current_entropy_objects '
                    "WHERE session_id = :sid AND detector_id = 'temporal_behavior'"
                ),
                {"sid": session_id},
            ).all()
    finally:
        mgr.close()
    for r in rows:
        if table_substr in r.target and r.target.endswith("." + column):
            return float(r.score)
    return None


@pytest.mark.llm
def test_teach_concept_property_drops_temporal_conflict() -> None:
    """concept_property teach-closure HARNESS for temporal_behavior — awaiting a mislabel corpus.

    The teach mechanism (``teach_concept_property_and_rerun``: a workspace-scoped
    ``concept_property`` overlay flips a concept's ``temporal_behavior``, the re-run's
    ontology_prior leans the taught way) is wired and exercised. But it can only CLOSE a
    conflict where the prior and the LLM claim DISAGREE — and curated finance data produces
    none (e2e 2026-06-09: on ``trial_balance.debit_balance`` BOTH witnesses name-anchor to
    stock → C≈0, nothing to close; and teaching ``account_balance→additive`` would INDUCE a
    conflict, not close one). A real two-witness teach-closure needs a prior≠claim mislabel
    column (a column the LLM reads correctly while its concept's declared behaviour disagrees)
    — deferred to the stock/flow mislabel corpus (DAT-450) / the reality witness (DAT-491).
    Until then this skips when no baseline conflict exists, keeping the harness wired.
    """
    if not (DATA_DIR / _TB_STRATEGY).exists():
        pytest.skip(
            f"no data for {_TB_STRATEGY}; run `python -m calibration.runner {_TB_STRATEGY}` first"
        )

    sidecar = runner_mod.sidecar_path(_TB_STRATEGY)
    run = (
        runner_mod.CalibrationRun.from_json(sidecar.read_text())
        if sidecar.exists()
        else runner_mod.run_pipeline(_TB_STRATEGY)
    )

    before = _temporal_behavior_conflict(run.session_id, _TB_TABLE, _TB_COLUMN)
    if before is None or before <= _DROP_MARGIN:
        pytest.skip(
            f"no prior≠claim conflict on {_TB_TABLE}.{_TB_COLUMN} (both witnesses name-anchor "
            "to stock — the DAT-491 boundary) → nothing to close; needs a mislabel corpus"
        )

    runner_mod.teach_concept_property_and_rerun(run, concept=_TB_CONCEPT, value="additive")

    after = _temporal_behavior_conflict(run.session_id, _TB_TABLE, _TB_COLUMN)
    assert after is not None, "temporal_behavior object vanished after the teach re-run"
    # Teach-closure: the taught concept behaviour makes the ontology_prior agree with the
    # LLM claim, so the pooled conflict drops. Signed-delta grammar, never a point threshold.
    assert after < before - _DROP_MARGIN, (
        f"teach did not close the conflict: C {before:.3f} -> {after:.3f} "
        f"(delta {after - before:+.3f}, expected drop > {_DROP_MARGIN})"
    )


def _unit_entropy_detected_unit(
    session_id: str, table_substr: str, column: str
) -> tuple[float, str | None] | None:
    """Head-resolved (score, evidence.detected_unit) for a column's unit_entropy object."""
    runner_mod.bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            read_schema = read_schema_name_for(
                str(s.execute(text("SELECT current_schema()")).scalar())
            )
            rows = s.execute(
                text(
                    f'SELECT target, score, evidence FROM "{read_schema}".current_entropy_objects '
                    "WHERE session_id = :sid AND detector_id = 'unit_entropy'"
                ),
                {"sid": session_id},
            ).all()
    finally:
        mgr.close()
    for r in rows:
        if table_substr in r.target and r.target.endswith("." + column):
            ev = r.evidence[0] if isinstance(r.evidence, list) and r.evidence else {}
            return float(r.score), ev.get("detected_unit")
    return None


@pytest.mark.llm
def test_teach_unit_lands_declaration() -> None:
    """A unit teach makes the column's unit LAND (DAT-428): unit_entropy evidence
    ``detected_unit`` goes ``None`` -> the taught unit after the re-run.

    On this financial data unit_entropy already scores ~0 ("inferred_from_dimension" —
    the unit is resolvable from a sibling currency column), so the teach's observable is
    the EXPLICIT declaration landing on the column, not a score drop. The applier→reader
    loop is proven deterministically in the engine (test_overlay + test_typing_phase's
    TestApplyUnitOverrides); this is the end-to-end confirmation through real Temporal.
    """
    if not (DATA_DIR / _UNIT_STRATEGY).exists():
        pytest.skip(
            f"no data for {_UNIT_STRATEGY}; run `python -m calibration.runner {_UNIT_STRATEGY}`"
        )

    sidecar = runner_mod.sidecar_path(_UNIT_STRATEGY)
    run = (
        runner_mod.CalibrationRun.from_json(sidecar.read_text())
        if sidecar.exists()
        else runner_mod.run_pipeline(_UNIT_STRATEGY)
    )

    before = _unit_entropy_detected_unit(run.session_id, _UNIT_TABLE, _UNIT_COLUMN)
    if before is None:
        pytest.skip(f"unit_entropy did not fire on {_UNIT_TABLE}.{_UNIT_COLUMN} (not a measure?)")
    _, before_unit = before
    assert before_unit is None, (
        f"{_UNIT_TABLE}.{_UNIT_COLUMN} already has a declared unit {before_unit!r}; "
        "pick a column with no declared unit so the teach has something to land"
    )

    runner_mod.teach_unit_and_rerun(run, table=_UNIT_TABLE, column=_UNIT_COLUMN, unit=_TAUGHT_UNIT)

    after = _unit_entropy_detected_unit(run.session_id, _UNIT_TABLE, _UNIT_COLUMN)
    assert after is not None, "unit_entropy object vanished after the teach re-run"
    _, after_unit = after
    # The taught unit lands on the already-typed numeric column — the dead link
    # ("nothing writes overrides.units") is closed. Independent of type-pattern matching.
    assert after_unit == _TAUGHT_UNIT, (
        f"unit teach did not land: detected_unit {before_unit!r} -> {after_unit!r}"
    )
