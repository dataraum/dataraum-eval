"""DAT-687: why does accounts_payable read -616,140.53 where AR reads exactly right?

Same extract shape, same view, same period filter — one lands on ground truth to
the cent, the other is 119.7% off with the wrong sign. Read the rows underneath.
"""

from __future__ import annotations

import sys

from calibration import runner as runner_mod
from calibration.tools._runs import load_run


def main() -> None:
    strategy = sys.argv[1] if len(sys.argv) > 1 else "clean"
    load_run(strategy)
    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:
            cursor.execute("""
                SELECT account_id__name, account_id__account_type,
                       COUNT(*) AS n_periods,
                       MIN(period) AS first_period, MAX(period) AS last_period
                FROM enriched_balance_sheet
                GROUP BY 1, 2 ORDER BY 2, 1
            """)
            print("enriched_balance_sheet accounts:")
            for r in cursor.fetchall():
                print(f"  {str(r[1]):<12} {r[0]:<28} n={r[2]:<3} {r[3]} … {r[4]}")

            cursor.execute("SELECT MAX(period) FROM enriched_balance_sheet")
            last = cursor.fetchone()[0]
            print(f"\nMAX(period) = {last}")

            for label, names in (
                ("AR", "('Accounts Receivable','Trade Receivables','Other Receivables')"),
                ("AP", "('Accounts Payable','Trade Payables')"),
            ):
                cursor.execute(f"""
                    SELECT account_id__name, period, ending_balance
                    FROM enriched_balance_sheet
                    WHERE account_id__name IN {names}
                    ORDER BY account_id__name, period
                """)
                rows = cursor.fetchall()
                print(f"\n{label} rows ({len(rows)}) — last 4 periods each:")
                for r in rows[-8:]:
                    print(f"  {r[0]:<24} {r[1]}  ending_balance={float(r[2]):>16,.2f}")
                cursor.execute(f"""
                    SELECT SUM(ending_balance) FROM enriched_balance_sheet
                    WHERE account_id__name IN {names}
                      AND period = (SELECT MAX(period) FROM enriched_balance_sheet)
                """)
                print(f"  → extract value at MAX(period): {float(cursor.fetchone()[0]):,.2f}")
    finally:
        shutdown_worker_substrate(manager)


if __name__ == "__main__":
    main()
