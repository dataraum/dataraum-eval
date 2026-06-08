#!/usr/bin/env python
"""Dump the loss-derived intent readiness for a strategy (DAT-442 rebaseline tool).

Reads the persisted ``EntropyObjectRecord`` rows of a completed calibration run,
assembles the loss-only readiness context (the SAME path ``conftest._assemble_readiness``
feeds the intent-readiness floor test), and prints per-(table, column) and per-endpoint
``{intent: band}``. Use it to rebaseline ``calibration/intent_readiness.yaml`` to what the
loss table actually produces — observed, not hand-tuned.

    python scripts/dump_intent_readiness.py detection-v1
    python scripts/dump_intent_readiness.py clean

Requires the run's sidecar (``output/<strategy>/calibration_run.json``) — run the
pipeline first (``python -m calibration.runner <strategy>``).
"""

from __future__ import annotations

import sys

import yaml

from calibration import runner as runner_mod


def _strip_source_prefix(name: str) -> str:
    return name.split("__", 1)[1] if "__" in name else name


_RANK = {"ready": 0, "investigate": 1, "blocked": 2}


def dump(strategy: str) -> dict[str, object]:
    """Return {column: {table.col: {intent: band}}, relationship: {...}} for a strategy."""
    sidecar = runner_mod.sidecar_path(strategy)
    if not sidecar.exists():
        raise SystemExit(f"no run for {strategy} — run `python -m calibration.runner {strategy}`")
    run = runner_mod.CalibrationRun.from_json(sidecar.read_text())
    runner_mod.bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.db_models import EntropyObjectRecord
    from dataraum.entropy.models import EntropyObject, parse_relationship_target
    from dataraum.entropy.views.readiness_context import assemble_readiness_context
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as session:
            records = list(
                session.execute(
                    select(EntropyObjectRecord).where(
                        EntropyObjectRecord.session_id == run.session_id
                    )
                ).scalars()
            )
            objects = [
                EntropyObject(
                    object_id=r.object_id,
                    layer=r.layer,
                    dimension=r.dimension,
                    sub_dimension=r.sub_dimension,
                    target=r.target,
                    score=r.score,
                    evidence=r.evidence if isinstance(r.evidence, list) else [],
                    detector_id=r.detector_id,
                )
                for r in records
            ]
            ctx = assemble_readiness_context(objects)
            table_names = {t.table_id: t.table_name for t in session.execute(select(Table)).scalars()}
            col_names = {
                c.column_id: (table_names.get(c.table_id, ""), c.column_name)
                for c in session.execute(select(Column)).scalars()
            }
    finally:
        mgr.close()

    columns: dict[str, dict[str, str]] = {}
    relationships: dict[str, dict[str, str]] = {}
    for target, col in ctx.columns.items():
        intents = {i.intent_name: i.readiness for i in col.intents}
        if target.startswith("column:"):
            ref = target.removeprefix("column:")
            if "." in ref:
                tbl, column = ref.split(".", 1)
                columns[f"{_strip_source_prefix(tbl)}.{column}"] = intents
        elif target.startswith("relationship:"):
            pair = parse_relationship_target(target)
            if not pair:
                continue
            for col_id in pair:
                tbl, column = col_names.get(col_id, ("", ""))
                if not (tbl and column):
                    continue
                key = f"{_strip_source_prefix(tbl)}.{column}"
                existing = relationships.setdefault(key, {})
                for intent_name, band in intents.items():
                    if _RANK[band] > _RANK.get(existing.get(intent_name, "ready"), 0):
                        existing[intent_name] = band
    return {"column": columns, "relationship": relationships}


if __name__ == "__main__":
    strategy = sys.argv[1] if len(sys.argv) > 1 else "detection-v1"
    result = dump(strategy)
    print(f"# intent readiness (loss rollup) — strategy={strategy}")
    # only surface non-ready bands; ready is the default floor.
    for grain in ("column", "relationship"):
        nonready = {
            k: {i: b for i, b in v.items() if b != "ready"}
            for k, v in result[grain].items()  # type: ignore[union-attr]
        }
        nonready = {k: v for k, v in nonready.items() if v}
        print(f"\n## {grain} (non-ready only)")
        print(yaml.safe_dump(nonready, sort_keys=True, default_flow_style=False) or "  (all ready)")
