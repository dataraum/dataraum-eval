"""Schema + profile overview of a completed run — the practitioner's first look.

    uv run python -m calibration.tools.look <strategy>            # all typed tables
    uv run python -m calibration.tools.look <strategy> <table>    # one table's columns

Per table: row count, the identified time axis (``TableEntity.time_column``),
and the enriched view. Per column (single-table mode): resolved type, semantic
role/business name, null ratio, distinct count, top values, temporal bounds.
Read-only PG metadata; never touches the lake or an LLM.
"""

from __future__ import annotations

import argparse
from typing import Any

import yaml

from calibration.tools._runs import load_run, short, workspace_session


def _tables_overview(session: Any) -> list[dict[str, Any]]:
    from dataraum.analysis.semantic.db_models import TableEntity
    from dataraum.analysis.views.db_models import EnrichedView
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    tables = [t for t in session.execute(select(Table)).scalars() if t.layer == "typed"]
    col_count: dict[str, int] = {}
    for col in session.execute(select(Column)).scalars():
        col_count[col.table_id] = col_count.get(col.table_id, 0) + 1
    time_col = {
        e.table_id: e.time_column
        for e in session.execute(select(TableEntity)).scalars()
        if e.time_column
    }
    enriched = {
        ev.fact_table_id: ev.view_name for ev in session.execute(select(EnrichedView)).scalars()
    }
    return [
        {
            "table": short(t.table_name),
            "rows": t.row_count,
            "columns": col_count.get(t.table_id, 0),
            "time_column": time_col.get(t.table_id),
            "enriched_view": enriched.get(t.table_id),
        }
        for t in sorted(tables, key=lambda t: t.table_name)
    ]


def _table_detail(session: Any, table_name: str) -> dict[str, Any]:
    from dataraum.analysis.semantic.db_models import SemanticAnnotation, TableEntity
    from dataraum.analysis.statistics.db_models import StatisticalProfile
    from dataraum.analysis.temporal import TemporalColumnProfile
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    table = next(
        (
            t
            for t in session.execute(select(Table)).scalars()
            if t.layer == "typed" and short(t.table_name) == table_name
        ),
        None,
    )
    if table is None:
        raise SystemExit(f"no typed table named {table_name!r} in this run")

    columns = [c for c in session.execute(select(Column)).scalars() if c.table_id == table.table_id]
    col_ids = [c.column_id for c in columns]
    stats = {
        p.column_id: p
        for p in session.execute(
            select(StatisticalProfile).where(StatisticalProfile.column_id.in_(col_ids))
        ).scalars()
    }
    semantics = {
        a.column_id: a
        for a in session.execute(
            select(SemanticAnnotation).where(SemanticAnnotation.column_id.in_(col_ids))
        ).scalars()
    }
    temporal = {
        p.column_id: p
        for p in session.execute(
            select(TemporalColumnProfile).where(TemporalColumnProfile.column_id.in_(col_ids))
        ).scalars()
    }
    entity = next(
        (e for e in session.execute(select(TableEntity)).scalars() if e.table_id == table.table_id),
        None,
    )

    col_entries = []
    for col in sorted(columns, key=lambda c: c.column_position or 0):
        entry: dict[str, Any] = {"column": col.column_name, "type": col.resolved_type}
        ann = semantics.get(col.column_id)
        if ann:
            entry["semantic_role"] = ann.semantic_role
            entry["business_name"] = ann.business_name
        prof = stats.get(col.column_id)
        if prof:
            entry["null_ratio"] = prof.null_ratio
            entry["distinct_count"] = prof.distinct_count
            top = (prof.profile_data or {}).get("top_values") or []
            if top:
                entry["top_values"] = top[:5]
        temp = temporal.get(col.column_id)
        if temp:
            entry["temporal"] = {
                "min": str(temp.min_timestamp),
                "max": str(temp.max_timestamp),
                "granularity": temp.detected_granularity,
            }
        col_entries.append(entry)

    return {
        "table": short(table.table_name),
        "rows": table.row_count,
        "entity_type": entity.detected_entity_type if entity else None,
        "time_column": entity.time_column if entity else None,
        "columns": col_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy")
    parser.add_argument("table", nargs="?", default=None)
    args = parser.parse_args()

    run = load_run(args.strategy)
    with workspace_session() as session:
        if args.table:
            payload: dict[str, Any] = _table_detail(session, args.table)
        else:
            payload = {"session_id": run.session_id, "tables": _tables_overview(session)}
    print(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
