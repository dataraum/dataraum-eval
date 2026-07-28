"""DAT-687 fork: is the AP break the ENGINE's, or our GENERATOR's?

Compares the generator's own balance_sheet.csv against its own journal_lines.csv
for AR and AP — no engine in the loop. If the CSVs already disagree, the finding
is ours (testdata) and filing it against the engine would be wrong.
"""

from __future__ import annotations

import duckdb

DATA = "data/clean"


def main() -> None:
    con = duckdb.connect()
    for name in ("balance_sheet", "journal_lines", "chart_of_accounts", "journal_entries"):
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{DATA}/{name}.csv')")

    print("chart_of_accounts columns:",
          [r[0] for r in con.execute("DESCRIBE chart_of_accounts").fetchall()])
    print("balance_sheet columns:",
          [r[0] for r in con.execute("DESCRIBE balance_sheet").fetchall()])
    print()

    print("balance_sheet — Trade Payables / Trade Receivables by period (last 5):")
    rows = con.execute("""
        SELECT b.*, c.name FROM balance_sheet b
        JOIN chart_of_accounts c USING (account_id)
        WHERE c.name IN ('Trade Payables','Trade Receivables')
        ORDER BY c.name, b.period
    """).fetchall()
    cols = [d[0] for d in con.description]
    for r in rows[-10:]:
        print("  " + "  ".join(f"{c}={v}" for c, v in zip(cols, r, strict=False)))

    print("\njournal_lines cumulative over the fiscal window [2025-01-01, 2026-01-01):")
    for label, expr, names in (
        ("AR (debit-credit)", "SUM(debit) - SUM(credit)", "('Trade Receivables','Other Receivables')"),
        ("AP (credit-debit)", "SUM(credit) - SUM(debit)", "('Trade Payables',)"),
    ):
        names_sql = names.replace(",)", ")")
        got = con.execute(f"""
            SELECT {expr} FROM journal_lines j
            JOIN chart_of_accounts c USING (account_id)
            JOIN journal_entries e USING (entry_id)
            WHERE c.name IN {names_sql}
              AND e.date >= DATE '2025-01-01' AND e.date < DATE '2026-01-01'
        """).fetchone()[0]
        allt = con.execute(f"""
            SELECT {expr} FROM journal_lines j
            JOIN chart_of_accounts c USING (account_id)
            WHERE c.name IN {names_sql}
        """).fetchone()[0]
        print(f"  {label:<22} in-window={float(got):>16,.2f}   all-time={float(allt):>16,.2f}")


if __name__ == "__main__":
    main()
