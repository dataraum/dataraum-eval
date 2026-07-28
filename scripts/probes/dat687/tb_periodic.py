"""Is trial_balance periodic (movements) or cumulative (stock)? The decisive fact.

The failing check's own description claims 'both are stock-like snapshot views at
the same period'. If the TB is periodic, that premise is false and the check is a
false alarm on clean data — the stock-vs-flow class, not a data defect.
"""

from __future__ import annotations

import duckdb

DATA = "data/clean"


def main() -> None:
    con = duckdb.connect()
    for name in ("balance_sheet", "trial_balance", "chart_of_accounts",
                 "journal_lines", "journal_entries"):
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{DATA}/{name}.csv')")

    print("trial_balance columns:", [r[0] for r in con.execute("DESCRIBE trial_balance").fetchall()])

    rows = con.execute("""
        SELECT tb.period,
               tb.debit_balance - tb.credit_balance AS net_tb,
               bs.ending_balance,
               (SELECT SUM(j.debit) - SUM(j.credit)
                FROM journal_lines j JOIN journal_entries e USING (entry_id)
                WHERE j.account_id = tb.account_id
                  AND strftime(e.date, '%Y-%m') <= tb.period)              AS gl_cumulative,
               (SELECT SUM(j.debit) - SUM(j.credit)
                FROM journal_lines j JOIN journal_entries e USING (entry_id)
                WHERE j.account_id = tb.account_id
                  AND strftime(e.date, '%Y-%m') = tb.period)               AS gl_period_only
        FROM trial_balance tb
        JOIN balance_sheet bs ON bs.account_id = tb.account_id AND bs.period = tb.period
        WHERE tb.account_id = '1110'
        ORDER BY tb.period
    """).fetchall()

    print("\naccount 1110 (cash) — TB net vs BS ending vs GL:")
    print(f"  {'period':<10} {'net_tb':>16} {'bs_ending':>16} "
          f"{'gl_cumulative':>16} {'gl_period_only':>16}")
    for period, net_tb, bs_end, cum, per in rows:
        print(f"  {period:<10} {float(net_tb):>16,.2f} {float(bs_end):>16,.2f} "
              f"{float(cum or 0):>16,.2f} {float(per or 0):>16,.2f}")

    matches_period = sum(1 for _, n, _, _, p in rows if abs(float(n) - float(p or 0)) < 0.01)
    matches_cum = sum(1 for _, n, _, c, _ in rows if abs(float(n) - float(c or 0)) < 0.01)
    bs_matches_cum = sum(1 for _, _, b, c, _ in rows if abs(float(b) - float(c or 0)) < 0.01)
    print(f"\n  TB net == GL period-only : {matches_period}/{len(rows)}   → PERIODIC")
    print(f"  TB net == GL cumulative  : {matches_cum}/{len(rows)}   → CUMULATIVE")
    print(f"  BS ending == GL cumulative: {bs_matches_cum}/{len(rows)}")


if __name__ == "__main__":
    main()
