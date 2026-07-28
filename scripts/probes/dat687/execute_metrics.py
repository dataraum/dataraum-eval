"""DAT-687 pre-flight 2: execute the ENGINE's own composed metric SQL on the lake.

The whole ticket rests on one assumption — that the formula SQL persisted per
metric is self-contained and runnable against the run's lake. Prove or kill it
here, read-only and free, before designing the oracle around it.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.tools._runs import load_run, workspace_session


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    load_run(strategy)

    with workspace_session() as session:
        snippets = session.execute(text("""
            SELECT source, sql FROM sql_snippets
            WHERE snippet_type = 'formula' AND source LIKE 'graph:%'
            ORDER BY source
        """)).all()

    print(f"{len(snippets)} formula snippets\n")
    print("--- first SQL verbatim ---")
    print(snippets[0].source)
    print(snippets[0].sql)
    print("--------------------------\n")

    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            for s in snippets:
                metric = s.source.removeprefix("graph:")
                try:
                    cursor.execute(s.sql)
                    rows = cursor.fetchall()
                    desc = [d[0] for d in cursor.description]
                    print(f"  {metric:<24} OK   cols={desc} rows={len(rows)} "
                          f"first={rows[0] if rows else None}")
                except Exception as exc:  # noqa: BLE001 — this IS the finding
                    print(f"  {metric:<24} FAIL {type(exc).__name__}: "
                          f"{str(exc).splitlines()[0][:120]}")
    finally:
        shutdown_worker_substrate(manager)


if __name__ == "__main__":
    main()
