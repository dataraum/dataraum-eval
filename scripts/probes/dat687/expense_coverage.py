"""DAT-687 finding: is the expense side grounded by TYPE or by account-name lists?

Revenue's extract predicates on the typed `account_id__account_type`; every
expense-side extract enumerates account NAMES. This measures the consequence
exactly: which expense accounts land in no extract, and how much money that is.
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
            SELECT concept, where_predicates
            FROM "{read_schema}".current_groundings
            WHERE statement = 'income_statement'
        """)).all()

    named: dict[str, list[str]] = {}
    typed: list[str] = []
    for r in rows:
        preds = json.loads(r.where_predicates) if r.where_predicates else []
        for p in preds or []:
            s = str(p)
            if "account_id__account_type" in s:
                typed.append(f"{r.concept}: {s}")
            elif "account_id__name IN" in s:
                inner = s.split("IN (", 1)[1].rsplit(")", 1)[0]
                named.setdefault(r.concept, []).extend(
                    part.strip().strip("'") for part in inner.split("','")
                )

    print("extracts predicating on the TYPED account_type column:")
    for t in sorted(typed):
        print(f"  {t}")
    print("\nextracts enumerating account NAMES:")
    covered: set[str] = set()
    for concept, names in sorted(named.items()):
        covered |= set(names)
        print(f"  {concept}: {len(names)} name(s)")

    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            cursor.execute("""
                SELECT account_id__name,
                       COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0) AS net
                FROM enriched_journal_lines
                WHERE account_id__account_type = 'expense'
                GROUP BY 1 ORDER BY 2 DESC
            """)
            expense_rows = cursor.fetchall()
            cursor.execute("""
                SELECT COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0)
                FROM enriched_journal_lines
                WHERE account_id__account_type = 'expense'
            """)
            total_expense = float(cursor.fetchone()[0])
    finally:
        shutdown_worker_substrate(manager)

    print(f"\nexpense accounts in the data (account_type='expense'): {len(expense_rows)}")
    hit = miss = 0.0
    missed: list[tuple[str, float]] = []
    for name, net in expense_rows:
        if name in covered:
            hit += float(net)
        else:
            miss += float(net)
            missed.append((name, float(net)))

    print(f"\ntotal expense (typed)          {total_expense:>16,.2f}")
    print(f"captured by a name list        {hit:>16,.2f}  ({hit / total_expense * 100:.1f}%)")
    print(f"captured by NO extract         {miss:>16,.2f}  ({miss / total_expense * 100:.1f}%)")
    print(f"\nexpense accounts no extract names ({len(missed)}):")
    for name, net in sorted(missed, key=lambda x: -x[1]):
        print(f"  {name:<34} {net:>14,.2f}")


if __name__ == "__main__":
    main()
