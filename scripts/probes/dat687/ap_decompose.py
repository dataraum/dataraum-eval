"""DAT-687: decompose the AP gap into scope / window / sign — three separate facts.

Only the last two are the engine's. Filing the first would be filing OUR metric
definition against them.
"""

from __future__ import annotations

import duckdb

DATA = "data/clean"
WINDOW = ("2025-01-01", "2026-01-01")


def main() -> None:
    con = duckdb.connect()
    for name in ("balance_sheet", "journal_lines", "chart_of_accounts", "journal_entries"):
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{DATA}/{name}.csv')")

    print("accounts the two sides call 'AP':")
    for acct in ("2110", "2120"):
        row = con.execute(
            f"SELECT account_id, name, account_type FROM chart_of_accounts "
            f"WHERE account_id = '{acct}'"
        ).fetchone()
        print(f"  golden SQL _AP_ACCOUNTS: {row}")
    print("  engine extract name list:  ('Accounts Payable','Trade Payables')")

    def gl(names_or_ids: str, *, by: str, window: bool) -> float:
        where = f"c.{by} IN ({names_or_ids})"
        win = (f"AND e.date >= DATE '{WINDOW[0]}' AND e.date < DATE '{WINDOW[1]}'"
               if window else "")
        return float(con.execute(f"""
            SELECT SUM(j.credit) - SUM(j.debit) FROM journal_lines j
            JOIN chart_of_accounts c USING (account_id)
            JOIN journal_entries e USING (entry_id)
            WHERE {where} {win}
        """).fetchone()[0])

    truth_set = "'2110','2120'"
    engine_set = "'Accounts Payable','Trade Payables'"

    print("\ncredit-debit over the GL, credit-natural (positive = a payable):")
    print(f"  truth set  (2110,2120)  in-window  {gl(truth_set, by='account_id', window=True):>14,.2f}"
          "   ← ground_truth.ending_ap_balance")
    print(f"  truth set  (2110,2120)  all-time   {gl(truth_set, by='account_id', window=False):>14,.2f}")
    print(f"  engine set (names)      in-window  {gl(engine_set, by='name', window=True):>14,.2f}")
    print(f"  engine set (names)      all-time   {gl(engine_set, by='name', window=False):>14,.2f}"
          "   ← what the engine's extract returns (negated)")

    scope = gl(truth_set, by="account_id", window=True) - gl(engine_set, by="name", window=True)
    window_effect = gl(engine_set, by="name", window=True) - gl(engine_set, by="name", window=False)
    print("\ndecomposition of the 3,745,513.61 gap (truth 3,129,373.08 vs engine -616,140.53):")
    print(f"  scope  (accounts truth counts that the engine's name list misses) {scope:>14,.2f}")
    print(f"  window (fiscal-year end vs MAX(period) = all-time)                {window_effect:>14,.2f}")
    print(f"  sign   (liability returned credit-negative into a ratio)          {2 * gl(engine_set, by='name', window=False):>14,.2f}")

    print("\nwhich accounts the engine's name list misses:")
    rows = con.execute(f"""
        SELECT c.account_id, c.name, SUM(j.credit) - SUM(j.debit) AS bal
        FROM journal_lines j JOIN chart_of_accounts c USING (account_id)
        JOIN journal_entries e USING (entry_id)
        WHERE c.account_id IN ({truth_set})
          AND e.date >= DATE '{WINDOW[0]}' AND e.date < DATE '{WINDOW[1]}'
        GROUP BY 1, 2 ORDER BY 1
    """).fetchall()
    for r in rows:
        mark = "in engine list" if r[1] in ("Accounts Payable", "Trade Payables") else "MISSED"
        print(f"  {r[0]}  {r[1]:<24} {float(r[2]):>14,.2f}   {mark}")


if __name__ == "__main__":
    main()
