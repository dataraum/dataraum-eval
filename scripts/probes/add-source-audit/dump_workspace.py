"""Dump EVERY workspace surface add_source wrote, for one strategy.

Not a contract, not an oracle — a census. The question is: after a full
add_source run, which surfaces did the engine populate, which did it leave
empty, and what is in them? Anything that is empty on a real 9-table corpus is
either out of slice or a bug, and we cannot tell which without looking.

Raw tables hold every run's rows by design; the head-resolved ``current_*``
views in the read schema are the reader surface. Both are printed, because the
gap between them is itself a finding (a phase that wrote rows nobody promoted
looks identical to a phase that ran, unless you compare).

    uv run python scripts/probes/add-source-audit/dump_workspace.py rel-f1
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session


def _count(session, schema: str, name: str) -> int | None:
    try:
        n = session.execute(text(f'SELECT count(*) FROM "{schema}"."{name}"')).scalar()  # noqa: S608
    except Exception as err:  # noqa: BLE001 — a census must not stop at one bad view
        print(f"  !! {schema}.{name}: {type(err).__name__}: {str(err)[:120]}")
        session.rollback()
        return None
    return int(n or 0)


def main(strategy: str) -> None:
    load_run(strategy)
    with workspace_session() as session:
        ws = session.execute(text("SELECT current_schema()")).scalar()
        schemas = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name NOT LIKE 'pg_%' AND schema_name <> 'information_schema' "
                    "ORDER BY schema_name"
                )
            ).fetchall()
        ]
        print(f"# workspace schema: {ws}")
        print(f"# schemas present: {', '.join(schemas)}\n")

        rows = session.execute(
            text(
                "SELECT table_schema, table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = ANY(:s) ORDER BY table_schema, table_type, table_name"
            ),
            {"s": schemas},
        ).fetchall()

        by_schema: dict[str, list[tuple[str, str, int | None]]] = {}
        for schema, name, kind in rows:
            by_schema.setdefault(schema, []).append((name, kind, _count(session, schema, name)))

        for schema, entries in by_schema.items():
            print(f"\n## {schema}")
            for name, kind, n in sorted(entries):
                if n is None:
                    continue
                tag = "" if kind == "BASE TABLE" else " (view)"
                flag = "   <-- EMPTY" if n == 0 else ""
                print(f"  {name:<44}{tag:<8} {n:>8,}{flag}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("strategy")
    main(**vars(p.parse_args()))
