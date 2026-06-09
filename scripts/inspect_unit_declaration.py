"""Inspect unit_entropy (unit_declaration) scores + table naming for a session.

Reads the head-resolved entropy objects for a known session and prints, for each
unit_entropy object, its target + score + unit_status evidence, alongside the raw
Table.table_name values. Tells us (a) the stored table-name format the unit teach
overlay key must match (``_apply_unit_overrides`` builds ``f"{table_name}.{column}"``)
and (b) which measure columns score "missing" (the teachable U-drop).
"""

from __future__ import annotations

import sys

from calibration import runner as runner_mod

SESSION = sys.argv[1] if len(sys.argv) > 1 else "a0eda213-f77a-47eb-800c-f4ad8227cca4"


def main() -> None:
    runner_mod.bootstrap_engine()
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.storage import Table
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import select, text

    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            print("=== Table.table_name values ===")
            for t in s.execute(select(Table)).scalars():
                print(f"  {t.table_name}")
            read_schema = read_schema_name_for(
                str(s.execute(text("SELECT current_schema()")).scalar())
            )
            rows = s.execute(
                text(
                    f'SELECT target, score, evidence FROM "{read_schema}".current_entropy_objects '
                    "WHERE session_id = :sid AND detector_id = 'unit_entropy' ORDER BY score DESC"
                ),
                {"sid": SESSION},
            ).all()
            print(f"\n=== unit_entropy objects (n={len(rows)}), score DESC ===")
            for r in rows:
                ev = r.evidence[0] if isinstance(r.evidence, list) and r.evidence else {}
                status = ev.get("unit_status")
                unit = ev.get("detected_unit")
                conf = ev.get("unit_confidence")
                print(
                    f"  score={float(r.score):.3f}  status={status!r:24} "
                    f"unit={unit!r} conf={conf}  {r.target}"
                )
    finally:
        mgr.close()


if __name__ == "__main__":
    main()
