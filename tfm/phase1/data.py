"""DAT-743 Phase 1: corpus loading + probe-specific shaping.

Shaping principles (each a recorded design decision, see PHASE1_FINDINGS):

- P3 tables are shaped LABEL-PRESERVING: entropy_map target_rows index the
  CSV data-row order, so only order-preserving ops are allowed (left m:1
  merges, column ops). No row drops, no sorts.
- Injected corpora carry type-corrupted cells (numbers replaced by strings).
  Columns that are >=80% numeric-parseable are coerced with
  pd.to_numeric(errors="coerce") — corrupted cells become NaN, which is
  exactly the trace a practitioner's pipeline would leave for the density
  model to see. Columns below the threshold stay categorical.
- Monthly series are built on a complete (account x month) grid with 0-fill
  for silent months (trial_balance only materializes periods with movement,
  generators.py:1090) and truncated to the fiscal window (receipts/payments
  posting up to 45 days late spill a 13th/49th period).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TFM_DATA = Path(__file__).resolve().parents[2] / "data" / "tfm"
SEED = 42

P1_CORPORA = [f"clean-48m-s{s}" for s in (42, 43, 44, 45, 46)]
P3_LEVELS = ("clean", "low", "medium", "high")


def load_table(corpus: str, name: str) -> pd.DataFrame:
    """Raw CSV read + per-column numeric coercion (>=80% parseable rule).

    Deliberately NOT skrub Cleaner here: Cleaner leaves mixed columns as
    object, which would ordinal-encode a 98%-numeric column and destroy its
    numeric structure for the density read-outs.
    """
    df = pd.read_csv(TFM_DATA / corpus / f"{name}.csv", dtype_backend="numpy_nullable")
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.notna().mean() >= 0.8:
                df[col] = coerced.astype("Float64")
    return df


# --------------------------------------------------------------- P1 series

def monthly_series(corpora: list[str] = P1_CORPORA, n_months: int = 48) -> pd.DataFrame:
    """Long frame: item_id ("s42/1010"), timestamp (month start), target.

    target = per-period net activity (debit_balance - credit_balance) on a
    complete monthly grid, 0-filled, fiscal window only.
    """
    frames = []
    for corpus in corpora:
        tb = load_table(corpus, "trial_balance")
        tb["period"] = pd.PeriodIndex(tb["period"].astype(str), freq="M")
        start = tb["period"].min()
        window = pd.period_range(start, periods=n_months, freq="M")
        tb = tb[tb["period"].isin(window)]
        tb["target"] = (tb["debit_balance"] - tb["credit_balance"]).astype(float)
        seed_tag = corpus.rsplit("-", 1)[-1]
        grid = pd.MultiIndex.from_product(
            [tb["account_id"].unique(), window], names=["account_id", "period"]
        )
        wide = (
            tb.set_index(["account_id", "period"])["target"]
            .reindex(grid, fill_value=0.0)
            .reset_index()
        )
        wide["item_id"] = seed_tag + "/" + wide["account_id"].astype(str)
        wide["timestamp"] = wide["period"].dt.to_timestamp()
        frames.append(wide[["item_id", "timestamp", "target"]])
    return pd.concat(frames, ignore_index=True)


def split_origin(series: pd.DataFrame, origin: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Context = first `origin` months per item, actuals = next 3 months."""
    out_ctx, out_fut = [], []
    for _, g in series.groupby("item_id", sort=False):
        g = g.sort_values("timestamp")
        out_ctx.append(g.iloc[:origin])
        out_fut.append(g.iloc[origin : origin + 3])
    return pd.concat(out_ctx, ignore_index=True), pd.concat(out_fut, ignore_index=True)


# --------------------------------------------------------------- P3 tables

P3_TABLES = ("journal_lines", "invoices", "payments", "bank_transactions", "trial_balance")

_OWN_PK = {
    "journal_lines": ["line_id"],
    "invoices": ["invoice_id"],
    "payments": ["payment_id"],
    "bank_transactions": ["transaction_id"],
    "trial_balance": [],
}


def p3_table(corpus: str, table: str, enriched: bool) -> pd.DataFrame:
    """One P3 scoring table, row-aligned with entropy_map target_rows.

    bare: the table minus its own primary key. enriched: + relational
    context that single-table density cannot see (the measured shaping axis):
      payments      + invoice amount/status (orphan FK -> NaN)
      journal_lines + account_type (orphan account_id -> NaN)
      trial_balance + sum_debit/sum_credit recomputed from POSTED lines
      invoices, bank_transactions: no enrichment defined (bare only)
    """
    df = load_table(corpus, table)
    drop = [c for c in _OWN_PK[table] if c in df.columns]
    # constant columns (e.g. currency=USD everywhere) carry no density signal
    # and break TabICL's conditional sampler — dropped, rows untouched
    drop += [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
    df = df.drop(columns=[*dict.fromkeys(drop)])

    if not enriched:
        return df

    if table == "payments":
        inv = load_table(corpus, "invoices")
        # injected 'high' renames some invoice columns (obscure_column_names)
        amount_col = "amount" if "amount" in inv.columns else None
        cols = ["invoice_id"] + ([amount_col] if amount_col else [])
        aux = inv[cols].rename(columns={amount_col: "inv_amount"} if amount_col else {})
        df = df.merge(aux, on="invoice_id", how="left", validate="m:1")
        if "inv_amount" in df.columns and "amount" in df.columns:
            df["pay_minus_inv"] = df["amount"].astype(float) - df["inv_amount"].astype(float)
    elif table == "journal_lines":
        acc = load_table(corpus, "chart_of_accounts")
        df = df.merge(
            acc[["account_id", "account_type"]], on="account_id", how="left", validate="m:1"
        )
    elif table == "trial_balance":
        agg = _posted_line_aggregates(corpus)
        df["period"] = df["period"].astype(str)
        df = df.merge(agg, on=["account_id", "period"], how="left", validate="m:1")
        for side in ("debit", "credit"):
            df[f"{side}_gap"] = df[f"{side}_balance"].astype(float) - df[f"sum_{side}"]
    return df


def _posted_line_aggregates(corpus: str) -> pd.DataFrame:
    """Recompute sum(debit)/sum(credit)/n_lines per (account_id, period) from
    POSTED journal entries — the DGP formula for trial_balance
    (generators.py:1055-1102)."""
    lines = load_table(corpus, "journal_lines")
    entries = load_table(corpus, "journal_entries")
    posted = entries[entries["status"] == "posted"][["entry_id", "date"]]
    joined = lines.merge(posted, on="entry_id", how="inner", validate="m:1")
    joined["period"] = pd.to_datetime(joined["date"]).dt.strftime("%Y-%m")
    for side in ("debit", "credit"):
        joined[side] = pd.to_numeric(joined[side], errors="coerce")
    agg = (
        joined.groupby(["account_id", "period"], as_index=False)
        .agg(sum_debit=("debit", "sum"), sum_credit=("credit", "sum"), n_lines=("debit", "size"))
    )
    return agg


def fill_cat_na(X: pd.DataFrame) -> pd.DataFrame:
    """Sentinel-fill missing categoricals ('missing') for the supervised
    frames — TabICL's sklearn encoder rejects object columns mixing NAType
    with str. Uniform across engines so the task stays identical."""
    out = X.copy()
    for col in out.columns:
        if not pd.api.types.is_numeric_dtype(out[col]):
            out[col] = out[col].astype(object).where(out[col].notna(), "missing")
    return out


# --------------------------------------------------------------- P2 tables

_RNG = np.random.default_rng(SEED)


def p2_net_amount(corpus: str = "p3-clean-s42", n: int = 4000) -> tuple[pd.DataFrame, pd.Series]:
    """Features for target net_amount; DGP formula = debit - credit only.

    Distractors: cost_center/account_type (event-assigned categoricals),
    entry month, plus one numeric and one categorical pure-noise column."""
    lines = load_table(corpus, "journal_lines")
    entries = load_table(corpus, "journal_entries")
    acc = load_table(corpus, "chart_of_accounts")
    df = lines.merge(entries[["entry_id", "date"]], on="entry_id", how="left", validate="m:1")
    df = df.merge(acc[["account_id", "account_type"]], on="account_id", how="left", validate="m:1")
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df = df.sample(n=min(n, len(df)), random_state=SEED).reset_index(drop=True)
    df["noise_num"] = _RNG.normal(size=len(df))
    df["noise_cat"] = _RNG.choice(list("ABCD"), size=len(df))
    y = pd.to_numeric(df["net_amount"], errors="coerce").astype(float)
    X = df[["debit", "credit", "cost_center", "account_type", "month", "noise_num", "noise_cat"]]
    X = X.assign(debit=pd.to_numeric(X["debit"], errors="coerce").astype(float),
                 credit=pd.to_numeric(X["credit"], errors="coerce").astype(float))
    return fill_cat_na(X), y


def p2_tb_balance(corpus: str = "p3-clean-s42", side: str = "debit") -> tuple[pd.DataFrame, pd.Series]:
    """Features for target trial_balance.{side}_balance; DGP formula =
    sum_{side} alone (grouping keys are not value drivers)."""
    tb = load_table(corpus, "trial_balance")
    tb["period"] = tb["period"].astype(str)
    acc = load_table(corpus, "chart_of_accounts")
    agg = _posted_line_aggregates(corpus)
    df = tb.merge(agg, on=["account_id", "period"], how="left", validate="m:1")
    df = df.merge(acc[["account_id", "account_type"]], on="account_id", how="left", validate="m:1")
    df["month"] = df["period"].str[-2:].astype(int)
    df["noise_num"] = _RNG.normal(size=len(df))
    y = df[f"{side}_balance"].astype(float)
    X = df[["sum_debit", "sum_credit", "n_lines", "account_type", "month", "noise_num"]]
    return fill_cat_na(X), y


# --------------------------------------------------------------- P4 frames

FX_PAIRS = ("EURUSD", "GBPUSD", "CHFUSD", "JPYUSD")


def monthly_fx(corpus: str) -> pd.DataFrame:
    """Monthly mean rate per USD-quoted pair, wide: period + fx_* columns."""
    fx = load_table(corpus, "fx_rates")
    fx["period"] = pd.to_datetime(fx["date"]).dt.strftime("%Y-%m")
    fx["pair"] = fx["from_ccy"].astype(str) + fx["to_ccy"].astype(str)
    fx = fx[fx["pair"].isin(FX_PAIRS)]
    wide = fx.pivot_table(index="period", columns="pair", values="rate", aggfunc="mean")
    wide.columns = [f"fx_{c}" for c in wide.columns]
    return wide.reset_index()


def p4_supervised(corpora: list[str] = P1_CORPORA) -> pd.DataFrame:
    """(item, month) rows: target + autoregressive base features + the two
    conditioning blocks (calendar 'month'; fx_* monthly means).

    Base features carry NO calendar information (lags/rolling stats only),
    so the 'month' block is the only calendar channel — the Q4 boost
    (q4_seasonal_boost=0.3) is its constructed signal. fx_* is the negative
    control: no fx->amount coupling exists in the DGP.
    """
    series = monthly_series(corpora)
    series = series.sort_values(["item_id", "timestamp"]).reset_index(drop=True)
    g = series.groupby("item_id", sort=False)["target"]
    for lag in (1, 2, 3):
        series[f"lag_{lag}"] = g.shift(lag)
    series["roll_mean_12"] = g.shift(1).rolling(12).mean().reset_index(level=0, drop=True)
    series["roll_std_12"] = g.shift(1).rolling(12).std().reset_index(level=0, drop=True)
    series["month"] = series["timestamp"].dt.month
    series["account_id"] = series["item_id"].str.split("/").str[1]
    series["seed"] = series["item_id"].str.split("/").str[0]

    fx_frames = []
    for corpus in corpora:
        wide = monthly_fx(corpus)
        wide["seed"] = corpus.rsplit("-", 1)[-1]
        fx_frames.append(wide)
    fx = pd.concat(fx_frames, ignore_index=True)
    series["period"] = series["timestamp"].dt.strftime("%Y-%m")
    out = series.merge(fx, on=["seed", "period"], how="left", validate="m:1")
    return out.dropna(subset=["lag_3", "roll_mean_12"]).reset_index(drop=True)


P4_BASE = ["account_id", "lag_1", "lag_2", "lag_3", "roll_mean_12", "roll_std_12"]
P4_CALENDAR = ["month"]
P4_FX = [f"fx_{p}" for p in FX_PAIRS]


# --------------------------------------------------------------- P6 / tiers

def supervised_regression(corpus: str = "p3-clean-s42") -> tuple[pd.DataFrame, pd.Series]:
    """journal_line_amount (phase0 shaping, corpus-parameterized): target
    net_amount, debit/credit dropped as the direct leak."""
    lines = load_table(corpus, "journal_lines")
    entries = load_table(corpus, "journal_entries").rename(columns={"status": "entry_status"})
    acc = load_table(corpus, "chart_of_accounts")
    df = lines.merge(entries, on="entry_id", how="left", validate="m:1")
    df = df.merge(
        acc[["account_id", "account_type", "currency"]].rename(
            columns={"currency": "account_currency"}
        ),
        on="account_id",
        how="left",
        validate="m:1",
    )
    dt = pd.to_datetime(df["date"])
    df["month"], df["day"], df["weekday"] = dt.dt.month, dt.dt.day, dt.dt.weekday
    y = df["net_amount"].astype(float)
    X = df.drop(
        columns=[c for c in ("debit", "credit", "net_amount", "line_id", "entry_id", "date") if c in df.columns]
    )
    return fill_cat_na(X), y


def supervised_classification(corpus: str = "p3-clean-s42") -> tuple[pd.DataFrame, pd.Series]:
    """invoice_status (phase0 shaping, corpus-parameterized): target status."""
    inv = load_table(corpus, "invoices")
    lines = load_table(corpus, "journal_lines")
    sums = lines.groupby("entry_id", as_index=False).agg(
        sum_debit=("debit", "sum"), sum_credit=("credit", "sum"), n_lines=("debit", "size")
    )
    df = inv.merge(sums, on="entry_id", how="left", validate="m:1")
    for col in ("date", "due_date"):
        df[col] = pd.to_datetime(df[col])
    df["days_until_due"] = (df["due_date"] - df["date"]).dt.days
    df["month"] = df["date"].dt.month
    y = df["status"].astype(str)
    X = df.drop(columns=["status", "invoice_id", "entry_id", "date", "due_date"])
    return fill_cat_na(X), y


def p6_table(corpus: str = "p3-clean-s42", n: int = 2000) -> pd.DataFrame:
    """Mixed numeric/categorical frame for imputation masking."""
    X, y = supervised_regression(corpus)
    df = X.assign(net_amount=y)
    keep = ["net_amount", "cost_center", "account_type", "account_currency", "month", "day", "weekday"]
    df = df[[c for c in keep if c in df.columns]]
    return df.sample(n=min(n, len(df)), random_state=SEED).reset_index(drop=True)
