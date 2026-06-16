"""Stock/flow clear-name accuracy — the DAT-445 ground-first gate's load-bearing residual.

The offline gate (DAT-445 probe, deleted — verdict in the scorecard) proved the family SEPARATES and the
reliability rig GENERALISES, conditional on one thing it could not measure offline: does
the LLM read stock/flow accurately from a CLEAR name? (kill-gate v3 says the LLM is
name-anchored → a clear name should yield the true read.) This e2e measures exactly that.

For each generated ``measure_probes`` column (true behaviour recorded in entropy_map),
compare the LLM's ``temporal_behavior_claim`` to the truth. High accuracy confirms the
build and the gate's optimistic bracket; a low number is the real CUT signal — and it
resolves cheap/early, the whole point of building the corpus residual-first.

Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

import pytest
import yaml
from dataraum.core.connections import ConnectionConfig, ConnectionManager
from dataraum.storage.read_views import read_schema_name_for
from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.conftest import DATA_DIR

_STRATEGY = "detection-stockflow-v1"
_MIN_ACCURACY = 0.70  # the gate's optimistic bracket floor; below this is the CUT signal


def _true_behaviours() -> dict[str, str]:
    """Ground-truth stock/flow per probe column, from the generated entropy_map."""
    emap = yaml.safe_load((DATA_DIR / _STRATEGY / "entropy_map.yaml").read_text())
    return {
        inj["target_column"]: inj["parameters"]["true_behavior"]
        for inj in emap["injections"]
        if inj.get("detector_id") == "temporal_behavior"
    }


def _llm_claims() -> dict[str, str | None]:
    """The LLM's ``temporal_behavior_claim`` per current measure_probes column.

    Head-resolved via ``current_semantic_annotations`` (semantic_annotations is
    column-grain, sealed under the per-table generation head): no session axis
    post-DAT-506 — the view returns the current annotation per column.
    """
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
                    "SELECT c.column_name AS col, sa.temporal_behavior_claim AS claim "
                    f'FROM "{read_schema}".current_semantic_annotations sa '
                    "JOIN columns c ON c.column_id = sa.column_id "
                    "JOIN tables t ON t.table_id = c.table_id "
                    "WHERE t.table_name LIKE '%measure_probes' "
                    "ORDER BY sa.annotated_at DESC"
                ),
            ).all()
    finally:
        mgr.close()
    claims: dict[str, str | None] = {}
    for r in rows:
        claims.setdefault(r.col, r.claim)  # most recent annotation per column
    return claims


@pytest.mark.llm
def test_llm_reads_clear_named_stock_flow_accurately() -> None:
    """Does the LLM read stock/flow from a clear name? (the gate's load-bearing residual)."""
    if not (DATA_DIR / _STRATEGY).exists():
        pytest.skip(
            f"no data for {_STRATEGY}; run `python -m calibration.runner {_STRATEGY}` first"
        )

    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        runner_mod.run_pipeline(_STRATEGY)  # produce the run + its sidecar
    runner_mod.activate_workspace(_STRATEGY)  # read this strategy's workspace (DAT-508)

    truth = _true_behaviours()
    claims = _llm_claims()
    assert truth, "no temporal_behavior probe labels in entropy_map"
    assert claims, "no temporal_behavior_claim annotations for measure_probes columns"

    graded = [(col, b, claims.get(col)) for col, b in truth.items() if col in claims]
    opinionated = [(c, b, cl) for c, b, cl in graded if cl in ("stock", "flow")]
    correct = [t for t in opinionated if t[1] == t[2]]
    accuracy = len(correct) / len(opinionated) if opinionated else 0.0
    unsure_rate = 1.0 - (len(opinionated) / len(graded)) if graded else 1.0

    print(
        f"\n[stockflow] clear-name accuracy={accuracy:.0%} over {len(opinionated)} opinionated "
        f"({len(correct)} correct); unsure/absent={unsure_rate:.0%} of {len(graded)} probes"
    )
    for col, b, cl in graded:
        if cl != b:
            print(f"  miss: {col}  true={b}  claim={cl}")

    assert opinionated, "the LLM abstained (unsure/absent) on every probe column"
    # Signed grammar against the gate's bracket floor, never a tuned point threshold.
    assert accuracy >= _MIN_ACCURACY, (
        f"clear-name stock/flow accuracy {accuracy:.0%} < {_MIN_ACCURACY:.0%} — the gate's "
        "load-bearing residual fails: the LLM does not read clear-named stock/flow (CUT signal)"
    )
