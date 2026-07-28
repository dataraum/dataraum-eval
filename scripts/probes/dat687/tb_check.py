"""DAT-687 leg (b): classify the one failing generated check on clean.

Known-open false-alarm classes on clean are DAT-875 (one-sided sign, deviation
exactly 2x|stored|) and DAT-876 (parent-exists). Is this one of them, a third, or
a true positive? Read the SQL and the worst legs.
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
        row = session.execute(text(
            "SELECT v.name, v.description, v.tolerance, v.check_type, v.expected_outcome, "
            "       r.sql_used, r.columns_used "
            "FROM validation_results r JOIN validations v USING (validation_id) "
            "WHERE v.superseded_at IS NULL AND v.name LIKE 'Trial balance derived%'"
        )).first()

    print(f"name:        {row.name}")
    print(f"description: {row.description}")
    print(f"tolerance:   {row.tolerance}   check_type: {row.check_type}")
    print(f"expected:    {row.expected_outcome}")
    print(f"columns:     {row.columns_used}")
    print(f"\nSQL:\n{row.sql_used}\n")

    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            cursor.execute(row.sql_used)
            cols = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            idx = cols.index("deviation")
            worst = sorted(rows, key=lambda r: -abs(float(r[idx] or 0)))[:8]
            print(f"legs: {len(rows)}; columns {cols}")
            print("worst 8:")
            for r in worst:
                print("  " + "  ".join(f"{c}={v}" for c, v in zip(cols, r, strict=False)))
            clean_legs = sum(1 for r in rows if abs(float(r[idx] or 0)) <= 0.01)
            print(f"\nlegs within tolerance: {clean_legs}/{len(rows)}")
    finally:
        shutdown_worker_substrate(manager)


if __name__ == "__main__":
    main()
