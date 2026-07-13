"""DAT-742 Phase 0: shape the month-end-close corpus into model-ready flat tables.

Reads the generated relational corpus (data/clean/), produces flat tables for the
engine toy runs, and prints a shaping ledger tagging each step [skrub] or [hand] —
the ledger is the raw material for the shaping-burden finding.

Outputs (tfm/output/shaped/):
  invoice_status.parquet        classification — target `status`
  journal_line_amount.parquet   regression     — target `net_amount`
  monthly_account_series.parquet  P1 substrate — account x period net balance
  manifest.yaml                 table -> task/target/feature summary
"""

from pathlib import Path

import pandas as pd
import yaml
from skrub import AggJoiner, Cleaner, DatetimeEncoder

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "clean"
OUT = REPO / "tfm" / "output" / "shaped"

LEDGER: list[str] = []


def step(tag: str, msg: str) -> None:
    LEDGER.append(f"[{tag}] {msg}")
    print(f"[{tag}] {msg}")


def load(name: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{name}.csv")
    df = Cleaner().fit_transform(df)
    step("skrub", f"{name}: Cleaner — dtype inference + datetime parsing ({len(df)} rows)")
    return df


def encode_dates(df: pd.DataFrame, col: str) -> pd.DataFrame:
    enc = DatetimeEncoder(resolution="day", add_weekday=True, add_total_seconds=True)
    feats = enc.fit_transform(df[col])
    step("skrub", f"DatetimeEncoder on {col} -> {list(feats.columns)}")
    return pd.concat([df.drop(columns=[col]), feats], axis=1)


def build_invoice_status(invoices: pd.DataFrame, journal_lines: pd.DataFrame) -> pd.DataFrame:
    aj = AggJoiner(
        aux_table=journal_lines,
        operations=["sum", "count"],
        main_key="entry_id",
        aux_key="entry_id",
        cols=["debit", "credit"],
    )
    df = aj.fit_transform(invoices)
    step("skrub", "AggJoiner journal_lines->invoices on entry_id (sum/count debit, credit)")

    df["days_until_due"] = (df["due_date"] - df["date"]).dt.days
    step("hand", "engineered days_until_due = due_date - date (pandas arithmetic)")

    df = encode_dates(df, "date")
    df = df.drop(columns=["invoice_id", "entry_id", "due_date"])
    step("hand", "dropped identifier/leak columns: invoice_id, entry_id, due_date")
    return df


def build_journal_line_amount(
    journal_lines: pd.DataFrame, journal_entries: pd.DataFrame, accounts: pd.DataFrame
) -> pd.DataFrame:
    df = journal_lines.merge(
        journal_entries.rename(columns={"status": "entry_status"}), on="entry_id", how="left"
    )
    df = df.merge(
        accounts.rename(columns={"name": "account_name", "currency": "account_currency"})[
            ["account_id", "account_name", "account_type", "account_currency"]
        ],
        on="account_id",
        how="left",
    )
    step(
        "hand",
        "exact FK joins journal_lines->journal_entries (entry_id), ->chart_of_accounts "
        "(account_id) via pandas merge — skrub's Joiner is a *fuzzy* joiner, wrong tool "
        "for exact FKs",
    )

    df = df.drop(columns=["debit", "credit"])
    step("hand", "dropped debit/credit — target net_amount = debit - credit, direct leak")

    df = encode_dates(df, "date")
    df = df.drop(columns=["line_id", "entry_id"])
    step("hand", "dropped identifier columns: line_id, entry_id")
    return df


def build_monthly_series(trial_balance: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    df = trial_balance.merge(
        accounts[["account_id", "name", "account_type"]], on="account_id", how="left"
    )
    step("hand", "exact FK join trial_balance->chart_of_accounts via pandas merge")

    df["net_balance"] = df["debit_balance"] - df["credit_balance"]
    df["period"] = pd.PeriodIndex(df["period"], freq="M").to_timestamp()
    step("hand", "net_balance = debit_balance - credit_balance; period -> timestamp")
    return df.sort_values(["account_id", "period"]).reset_index(drop=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    invoices = load("invoices")
    journal_lines = load("journal_lines")
    journal_entries = load("journal_entries")
    accounts = load("chart_of_accounts")
    trial_balance = load("trial_balance")

    tables = {
        "invoice_status": (build_invoice_status(invoices, journal_lines), "status"),
        "journal_line_amount": (
            build_journal_line_amount(journal_lines, journal_entries, accounts),
            "net_amount",
        ),
        "monthly_account_series": (build_monthly_series(trial_balance, accounts), "net_balance"),
    }

    manifest = {}
    for name, (df, target) in tables.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        manifest[name] = {
            "target": target,
            "rows": int(len(df)),
            "columns": {c: str(t) for c, t in df.dtypes.items()},
        }
        print(f"\n== {name}: {df.shape[0]} rows x {df.shape[1]} cols, target={target}")
        print(df.dtypes.to_string())

    (OUT / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))

    print("\n===== shaping ledger =====")
    skrub_n = sum(1 for line in LEDGER if line.startswith("[skrub]"))
    hand_n = sum(1 for line in LEDGER if line.startswith("[hand]"))
    print(f"{skrub_n} skrub steps, {hand_n} hand steps")


if __name__ == "__main__":
    main()
