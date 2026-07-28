"""DAT-687 leg (b) pre-flight: what does the validation surface offer for a re-run?"""

from __future__ import annotations

import sys

from sqlalchemy import text

from calibration.tools._runs import load_run, workspace_session


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    load_run(strategy)
    with workspace_session() as session:
        for table in ("validations", "validation_results"):
            cols = session.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t "
                "ORDER BY ordinal_position"
            ), {"t": table}).all()
            print(f"{table}: {[c[0] for c in cols]}\n")

        rows = session.execute(text(
            "SELECT source, check_type, COUNT(*) FROM validations "
            "WHERE superseded_at IS NULL GROUP BY 1,2 ORDER BY 1,2"
        )).all()
        print("validations by (source, check_type):")
        for r in rows:
            print(f"  {str(r[0]):<12} {r[1]:<12} {r[2]}")

        res = session.execute(text(
            "SELECT v.name, v.check_type, r.* FROM validation_results r "
            "JOIN validations v USING (validation_id) LIMIT 3"
        )).all()
        print(f"\nvalidation_results sample ({len(res)}):")
        for r in res:
            print(f"  {r}")

        n = session.execute(text(
            "SELECT COUNT(*), COUNT(sql_used) FROM validation_results"
        )).first()
        print(f"\nvalidation_results rows={n[0]}, with sql_used={n[1]}")


if __name__ == "__main__":
    main()
