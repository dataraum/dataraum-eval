"""Entropy scores + loss-rollup readiness for a completed run.

    uv run python -m calibration.tools.measure <strategy>
    uv run python -m calibration.tools.measure <strategy> --target <table.column>

Dataset mode: every column-scoped detector score (head-resolved, the same
``current_entropy_objects`` path the calibration tests read — never PhaseLog),
plus per-column intent readiness from the loss rollup (ready / investigate /
blocked; the Bayesian network is gone — DAT-442) and the band counts.

Target mode: one column's full evidence — every entropy object with its
witness claims, plus the persisted ``claim_witnesses`` provenance and the
per-intent readiness. The ``why``-equivalent of the retired MCP surface.
"""

from __future__ import annotations

import argparse
from typing import Any

import yaml

from calibration.tools._runs import load_run, short, workspace_session

_BAND_RANK = {"ready": 0, "investigate": 1, "blocked": 2}


def _dataset_view(strategy: str) -> dict[str, Any]:
    # Reuse the conftest read paths verbatim — these are the canonical score
    # and readiness sources (the sidecar exists, so no pipeline is triggered).
    from dataraum.entropy.loss import get_loss_config

    from calibration.conftest import _assemble_readiness, _load_scores_for_strategy

    scores = _load_scores_for_strategy(strategy)
    ctx, _col_names = _assemble_readiness(strategy)
    loss_config = get_loss_config()

    bands: dict[str, dict[str, str]] = {}
    drivers: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for target, col in ctx.columns.items():
        if not target.startswith("column:"):
            continue
        ref = target.removeprefix("column:")
        if "." not in ref:
            continue
        tbl, column = ref.split(".", 1)
        intents = {i.intent_name: i.readiness for i in col.intents}
        if any(band != "ready" for band in intents.values()):
            key = f"{short(tbl)}.{column}"
            bands[key] = intents
            # Banding drivers per non-ready intent: intent risk is the MAX over
            # measurements, so only a driver whose own contribution reaches a
            # non-ready band can have set (or would alone set) the band — those
            # are the measurements a prevention can be attributed to.
            drivers[key] = {
                intent.intent_name: [
                    {"detector": d.node, "impact": round(d.impact_delta, 4)}
                    for d in intent.drivers
                    if loss_config.band(d.impact_delta) != "ready"
                ]
                for intent in col.intents
                if intent.readiness != "ready"
            }

    worst = {
        key: max(intents.values(), key=lambda band: _BAND_RANK[band])
        for key, intents in bands.items()
    }
    return {
        "column_scores": [
            {"table": t, "column": c, "detector": d, "score": round(s, 4)}
            for (t, c, d), s in sorted(scores.column.items(), key=lambda kv: -kv[1])
        ],
        "relationship_scores": [
            {"table": t, "column": c, "detector": d, "score": round(s, 4)}
            for (t, c, d), s in sorted(scores.relationship.items(), key=lambda kv: -kv[1])
        ],
        "readiness": {
            "columns_blocked": sum(1 for band in worst.values() if band == "blocked"),
            "columns_investigate": sum(1 for band in worst.values() if band == "investigate"),
            "non_ready_intents": bands,
            "non_ready_drivers": drivers,
        },
    }


def _target_view(strategy: str, target: str) -> dict[str, Any]:
    from sqlalchemy import select

    from calibration.conftest import _assemble_readiness, _head_resolved_entropy_rows

    load_run(strategy)  # guard: the strategy's pipeline must have run (sidecar present)
    table_name, _, column_name = target.partition(".")
    if not column_name:
        raise SystemExit("--target must be <table.column>")

    objects: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    with workspace_session() as session:
        from dataraum.entropy.db_models import ClaimWitnessRecord
        from dataraum.storage.snapshot_head import MetadataSnapshotHead

        for row in _head_resolved_entropy_rows(session):
            if not row.target.startswith("column:"):
                continue
            ref = row.target.removeprefix("column:")
            if "." not in ref:
                continue
            tbl, col = ref.split(".", 1)
            if (short(tbl), col) != (table_name, column_name):
                continue
            objects.append(
                {
                    "detector": row.detector_id,
                    "dimension": f"{row.layer}.{row.dimension}.{row.sub_dimension}",
                    "score": round(row.score, 4),
                    "evidence": row.evidence,
                    "run_id": row.run_id,
                }
            )
        # Current witnesses = rows under any currently-promoted head (no session
        # axis post-DAT-506); mirrors the current_claim_witnesses view's filter.
        for rec in session.execute(
            select(ClaimWitnessRecord).where(
                ClaimWitnessRecord.run_id.in_(select(MetadataSnapshotHead.run_id))
            )
        ).scalars():
            ref = rec.target.removeprefix("column:")
            if "." not in ref:
                continue
            tbl, col = ref.split(".", 1)
            if (short(tbl), col) != (table_name, column_name):
                continue
            witnesses.append(
                {
                    "claim_field": rec.claim_field,
                    "witness": rec.witness_id,
                    "reliability": rec.reliability,
                    "distribution": rec.distribution,
                    "run_id": rec.run_id,
                }
            )

    ctx, _ = _assemble_readiness(strategy)
    intents: dict[str, str] = {}
    for tgt, col_result in ctx.columns.items():
        ref = tgt.removeprefix("column:")
        if "." in ref:
            tbl, col = ref.split(".", 1)
            if (short(tbl), col) == (table_name, column_name):
                intents = {i.intent_name: i.readiness for i in col_result.intents}
                break

    return {
        "target": target,
        "entropy_objects": sorted(objects, key=lambda o: -o["score"]),
        "claim_witnesses": witnesses,
        "intent_readiness": intents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy")
    parser.add_argument("--target", default=None, help="<table.column> for full evidence")
    args = parser.parse_args()

    load_run(args.strategy)  # fail loudly before any engine bootstrap
    payload = (
        _target_view(args.strategy, args.target) if args.target else _dataset_view(args.strategy)
    )
    print(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
