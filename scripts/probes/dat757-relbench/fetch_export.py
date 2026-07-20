"""DAT-757 RelBench fold — stage 1: fetch a RelBench database, export tables + FK truth.

Runs in an ephemeral dependency overlay (relbench needs pandas; the eval env is
polars-only) — stage 2 (fold + gate stack + grading) then works from the parquet
exports with the native env:

    uv run --with relbench --with pandas --with pyarrow \
        python scripts/probes/dat757-relbench/fetch_export.py rel-f1

Writes to corpora/relbench/<name>/ (gitignored, re-derivable):
    tables/<table>.parquet
    schema.json   — {table: {pkey, fkeys: {col: target_table}, time_col, n_rows}}

The declared pkey/fkey metadata IS the ground truth: after WE denormalize, every
FK becomes a folded-dimension exposure whose expected structure is derivable —
that is the whole point of the exercise (out-of-distribution data, in-distribution
truth). --max-rows samples oversized fact tables (fixed seed; FDs survive sampling).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MAX_ROWS_DEFAULT = 2_000_000
SEED = 757


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="e.g. rel-f1, rel-hm, rel-salt")
    ap.add_argument("--max-rows", type=int, default=MAX_ROWS_DEFAULT)
    args = ap.parse_args()

    from relbench.datasets import get_dataset  # noqa: PLC0415 (overlay-only import)

    ds = get_dataset(args.dataset, download=True)
    db = ds.get_db(upto_test_timestamp=False)

    out = Path("corpora/relbench") / args.dataset
    (out / "tables").mkdir(parents=True, exist_ok=True)

    schema: dict[str, dict] = {}
    for name, table in db.table_dict.items():
        df = table.df
        n_full = len(df)
        if n_full > args.max_rows:
            df = df.sample(args.max_rows, random_state=SEED)
        df.to_parquet(out / "tables" / f"{name}.parquet", index=False)
        schema[name] = {
            "pkey": table.pkey_col,
            "fkeys": dict(table.fkey_col_to_pkey_table),
            "time_col": table.time_col,
            "n_rows": len(df),
            "n_rows_full": n_full,
            "columns": [str(c) for c in df.columns],
        }
        print(f"  {name:28} {len(df):>10,} rows ({n_full:,} full)  "
              f"pkey={table.pkey_col}  fkeys={list(table.fkey_col_to_pkey_table)}")

    (out / "schema.json").write_text(json.dumps(schema, indent=2))
    print(f"\nexported -> {out}")


if __name__ == "__main__":
    main()
