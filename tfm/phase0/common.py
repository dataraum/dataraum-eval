"""DAT-742 Phase 0: shared helpers for the engine toy runs.

Each toy runner probes the engine's read-outs on the shaped corpus tables and
records one inventory row per read-out: ok / missing / error, wall seconds, note.
The merged rows become the engine x read-out inventory matrix.
"""

import json
import time
import traceback
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

REPO = Path(__file__).resolve().parents[2]
SHAPED = REPO / "tfm" / "output" / "shaped"
INVENTORY_DIR = REPO / "tfm" / "output" / "inventory"

SEED = 42
READ_OUTS = [
    "classification",
    "regression",
    "quantiles",
    "forecast",
    "anomaly",
    "imputation",
    "feature_importance",
]


def load_clf() -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_parquet(SHAPED / "invoice_status.parquet")
    y = df.pop("status")
    return df, y


def load_reg(n: int = 5000) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_parquet(SHAPED / "journal_line_amount.parquet")
    df = df.sample(min(n, len(df)), random_state=SEED).reset_index(drop=True)
    y = df.pop("net_amount")
    return df, y


def load_series() -> pd.DataFrame:
    return pd.read_parquet(SHAPED / "monthly_account_series.parquet")


def clf_split() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    X, y = load_clf()
    return train_test_split(X, y, test_size=0.25, random_state=SEED, stratify=y)


def reg_split(n: int = 5000) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    X, y = load_reg(n)
    return train_test_split(X, y, test_size=0.2, random_state=SEED)


class Inventory:
    """Collects read-out probe results for one engine and writes them to JSON."""

    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.rows: list[dict] = []

    def run(self, read_out: str, fn: Callable[[], str]) -> None:
        t0 = time.perf_counter()
        try:
            note = fn()
            status = "ok"
        except Exception as e:  # noqa: BLE001 — the error IS the inventory result
            note = f"{type(e).__name__}: {e}"
            status = "error"
            traceback.print_exc()
        seconds = round(time.perf_counter() - t0, 2)
        self.rows.append(
            {"read_out": read_out, "status": status, "seconds": seconds, "note": note}
        )
        print(f"[{self.engine}] {read_out}: {status} ({seconds}s) — {note}")

    def missing(self, read_out: str, note: str) -> None:
        self.rows.append({"read_out": read_out, "status": "missing", "seconds": 0, "note": note})
        print(f"[{self.engine}] {read_out}: missing — {note}")

    def save(self) -> None:
        INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
        out = INVENTORY_DIR / f"{self.engine}.json"
        out.write_text(json.dumps({"engine": self.engine, "rows": self.rows}, indent=2))
        print(f"[{self.engine}] inventory -> {out}")
