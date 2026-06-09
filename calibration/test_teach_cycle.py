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
        pytest.skip(f"no data for {_STRATEGY}; run `python -m calibration.runner {_STRATEGY}` first")

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
