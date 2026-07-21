"""Stock/flow two-witness recall + concept_property teach-closure (DAT-445).

The full arc on the generative corpus, the thing debit_balance structurally could not show
(both witnesses name-anchored): quiet → mislabel a concept → conflict → correct it → quiet.

A clearly-named stock probe column (e.g. ``closing_cash``) binds to a concept (``cash``,
point_in_time) and the LLM reads it as stock → the witnesses AGREE → quiet (precision).
Teaching ``concept_property cash→additive`` flips the ontology_prior to flow while the LLM
still reads stock → a genuine prior!=claim CONFLICT (recall — the two-witness model fires).
Teaching ``cash→point_in_time`` back makes the prior agree again → the conflict COLLAPSES
(teach-closure). Self-discovering: picks whatever probe column bound to a concept and stayed
quiet, so it is robust to the sampled draw. Three pipeline runs (baseline + mislabel + correct).

Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

import pytest
import yaml
from dataraum.core.connections import ConnectionConfig, ConnectionManager
from dataraum.storage.read_views import read_schema_name_for
from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.conftest import DATA_DIR, measured_rows, require_pipeline_run

_STRATEGY = "detection-stockflow-v1"
_MARGIN = 0.2  # anti-noise floor on the signed conflict deltas, NOT a point threshold

# true behaviour → the ontology temporal_behavior value (correct) and its mislabel.
_TRUE_VALUE = {"stock": "point_in_time", "flow": "additive"}
_MISLABEL = {"stock": "additive", "flow": "point_in_time"}


def _true_behaviours() -> dict[str, str]:
    emap = yaml.safe_load((DATA_DIR / _STRATEGY / "entropy_map.yaml").read_text())
    return {
        inj["target_column"]: inj["parameters"]["true_behavior"]
        for inj in emap["injections"]
        if inj.get("detector_id") == "temporal_behavior"
    }


def _probe_state() -> dict[str, tuple[str | None, float | None]]:
    """Per measure_probes column: (bound business_concept, head-resolved conflict C).

    Both reads are head-resolved (no session axis post-DAT-506): semantic
    annotations via ``current_semantic_annotations`` (column-grain generation
    head), the conflict via ``current_entropy_objects`` — so a teach re-run's
    fresh head replaces the prior run's rows.
    """
    runner_mod.bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            read_schema = read_schema_name_for(
                str(s.execute(text("SELECT current_schema()")).scalar())
            )
            concepts = s.execute(
                text(
                    "SELECT c.column_name AS col, sa.business_concept AS concept "
                    f'FROM "{read_schema}".current_semantic_annotations sa '
                    "JOIN columns c ON c.column_id = sa.column_id "
                    "JOIN tables t ON t.table_id = c.table_id "
                    "WHERE t.table_name LIKE '%measure_probes' "
                    "ORDER BY sa.annotated_at DESC"
                ),
            ).all()
            objs = s.execute(
                text(
                    "SELECT target, score, status, detector_id "
                    f'FROM "{read_schema}".current_entropy_objects '
                    "WHERE detector_id = 'temporal_behavior' "
                    "AND target LIKE '%measure_probes.%'"
                ),
            ).all()
    finally:
        mgr.close()

    concept_by_col: dict[str, str | None] = {}
    for r in concepts:
        concept_by_col.setdefault(r.col, r.concept)  # most recent annotation per column
    # MEASURED rows only (DAT-853): an abstained temporal_behavior row carries no conflict
    # score (float(None) would crash); a corrupt measured-NULL raises loud via measured_rows.
    conflict_by_col = {
        r.target.rsplit(".", 1)[-1]: float(r.score) for r in measured_rows(list(objs))
    }
    return {
        col: (concept_by_col.get(col), conflict_by_col.get(col))
        for col in set(concept_by_col) | set(conflict_by_col)
    }


@pytest.mark.llm
def test_stockflow_mislabel_recall_and_concept_teach_closure(strategy_name: str) -> None:
    """quiet → mislabel concept (recall) → correct concept (teach-closure)."""
    if strategy_name != _STRATEGY:
        pytest.skip(f"scoped to {_STRATEGY!r} — runs on its own --strategy pass only (DAT-797)")
    if not (DATA_DIR / _STRATEGY).exists():
        pytest.skip(
            f"no data for {_STRATEGY}; run `python -m calibration.runner {_STRATEGY}` first"
        )

    run = require_pipeline_run(_STRATEGY)

    truth = _true_behaviours()
    base = _probe_state()
    # A target: a probe column the LLM bound to a concept, quiet in the baseline (prior
    # agrees with the claim), with a known true behaviour to mislabel against.
    target = next(
        (
            col
            for col, (concept, conflict) in base.items()
            if concept and conflict is not None and conflict < _MARGIN and col in truth
        ),
        None,
    )
    if target is None:
        pytest.skip(
            "no quiet concept-bound probe column to mislabel — the LLM bound none of the "
            "measure_probes columns to a concept (or none stayed quiet); nothing to exercise"
        )
    concept = base[target][0]
    true_b = truth[target]
    before = base[target][1]
    assert concept is not None and before is not None
    print(f"\n[stockflow] target={target} concept={concept} true={true_b} baseline C={before:.3f}")

    # Mislabel the concept → the ontology_prior flips, the LLM still reads the true name.
    runner_mod.teach_concept_property_and_rerun(run, concept=concept, value=_MISLABEL[true_b])
    during = _probe_state().get(target, (None, None))[1]
    assert during is not None, "temporal_behavior object vanished after the mislabel re-run"
    print(f"[stockflow] after mislabel {concept}→{_MISLABEL[true_b]}: C={during:.3f}")

    # Correct the concept → the prior agrees again, the conflict collapses.
    runner_mod.teach_concept_property_and_rerun(run, concept=concept, value=_TRUE_VALUE[true_b])
    after = _probe_state().get(target, (None, None))[1]
    assert after is not None, "temporal_behavior object vanished after the correcting re-run"
    print(f"[stockflow] after correct {concept}→{_TRUE_VALUE[true_b]}: C={after:.3f}")

    # RECALL: mislabeling a concept makes the two-witness model fire (prior!=claim).
    assert during > before + _MARGIN, (
        f"mislabel did not raise conflict: C {before:.3f} -> {during:.3f} "
        f"(delta {during - before:+.3f}, expected rise > {_MARGIN})"
    )
    # TEACH-CLOSURE: correcting the concept collapses the conflict (signed-delta grammar).
    assert after < during - _MARGIN, (
        f"teach did not close the conflict: C {during:.3f} -> {after:.3f} "
        f"(delta {after - during:+.3f}, expected drop > {_MARGIN})"
    )
