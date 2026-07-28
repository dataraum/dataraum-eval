"""DAT-687 pre-flight 4: what each level-1 extract actually resolves to.

A metric being wrong is a headline; a metric being wrong *because this extract
binds these accounts* is a finding. Executes every extract snippet and prints its
grounded clause parts next to its value.
"""

from __future__ import annotations

import json
import sys

from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.tools._runs import load_run, workspace_session


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    load_run(strategy)

    with workspace_session() as session:
        from dataraum.storage.read_views import read_schema_name_for

        read_schema = read_schema_name_for(
            session.execute(text("SELECT current_schema()")).scalar()
        )
        rows = session.execute(text(f"""
            SELECT concept, statement, aggregation, relation, select_expr,
                   where_predicates, sql, failed
            FROM "{read_schema}".current_groundings
            ORDER BY concept
        """)).all()

    print(f"{len(rows)} groundings (extract snippets)\n")

    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            for r in rows:
                try:
                    cursor.execute(r.sql)
                    got = cursor.fetchone()
                    value = got[0] if got else None
                except Exception as exc:  # noqa: BLE001
                    value = f"FAIL {type(exc).__name__}: {str(exc).splitlines()[0][:60]}"
                shown = f"{value:,.2f}" if isinstance(value, (int, float)) else value
                print(f"{r.concept}  [{r.statement}/{r.aggregation}]"
                      + ("  FAILED-SNIPPET" if r.failed else ""))
                print(f"  value    {shown}")
                print(f"  relation {r.relation}")
                print(f"  select   {r.select_expr}")
                preds = json.loads(r.where_predicates) if r.where_predicates else []
                for p in preds or []:
                    print(f"  where    {str(p)[:200]}")
                print()
    finally:
        shutdown_worker_substrate(manager)


if __name__ == "__main__":
    main()
