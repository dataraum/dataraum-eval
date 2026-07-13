"""DAT-743 P6: imputation — mask known cells, measure recovery.

MCAR masks at 10% and 20% per column (seeded) on a mixed numeric/categorical
frame from the clean corpus. Engines: TabICL impute, TabPFN-extensions
impute (TabFM: no imputation read-out — recorded gap). Baselines: kNN
(on the ordinal-encoded matrix) and mean/mode.

Metrics in ORIGINAL space: NRMSE (RMSE/std) per numeric column, accuracy
per categorical column, averaged per kind over masked cells only.

Usage: uv run python p6_impute.py [--smoke] [--methods ...]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import baselines as bl
import data
import engines as eng
import metrics as mx
import results as rs

PROBE = "p6_impute"
SEED = 42
MASK_RATES = (0.1, 0.2)


def mask_mcar(df: pd.DataFrame, rate: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (masked frame, boolean mask of cells that were hidden)."""
    rng = np.random.default_rng(seed)
    mask = pd.DataFrame(rng.random(df.shape) < rate, columns=df.columns, index=df.index)
    mask &= df.notna()  # only mask observed cells
    out = df.mask(mask)
    return out, mask


def knn_impute(masked: pd.DataFrame) -> pd.DataFrame:
    enc, _, vocab = eng.encode_for_density(masked)
    filled = bl.knn_impute_numeric(pd.DataFrame(enc, columns=masked.columns))
    return eng.decode_from_density(filled.to_numpy(), masked, vocab)


METHODS = {
    "mean_mode": bl.mean_mode_impute,
    "knn": knn_impute,
    "tabicl2": lambda m: eng.ENGINES["tabicl2"].impute(m),
    "tabpfn3": lambda m: eng.ENGINES["tabpfn3"].impute(m),
}


def evaluate(truth: pd.DataFrame, filled: pd.DataFrame, mask: pd.DataFrame) -> dict:
    per_col: dict[str, dict] = {}
    num_scores, cat_scores = [], []
    for col in truth.columns:
        cells = mask[col].to_numpy()
        if cells.sum() == 0:
            continue
        kind = "numeric" if pd.api.types.is_numeric_dtype(truth[col]) else "categorical"
        res = mx.imputation_error(
            truth.loc[cells, col].to_numpy(), filled.loc[cells, col].to_numpy(), kind
        )
        per_col[col] = res
        (num_scores if kind == "numeric" else cat_scores).append(
            res.get("nrmse", res.get("accuracy"))
        )
    return {
        "nrmse_numeric_mean": float(np.mean(num_scores)) if num_scores else None,
        "acc_categorical_mean": float(np.mean(cat_scores)) if cat_scores else None,
        "per_column": per_col,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--methods", default=",".join(METHODS))
    args = ap.parse_args()

    truth = data.p6_table(n=300 if args.smoke else 2000)

    for rate in MASK_RATES[:1] if args.smoke else MASK_RATES:
        masked, mask = mask_mcar(truth, rate, SEED)
        for name in args.methods.split(","):
            config = {"mask_rate": rate, "n": len(truth), "smoke": args.smoke}
            try:
                with rs.timed() as t:
                    filled = METHODS[name](masked.copy())
                metrics = evaluate(truth, filled, mask)
            except Exception as exc:  # a failing read-out is a finding
                rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                continue
            rs.record(PROBE, name, config, metrics, latency_s=t["s"])


if __name__ == "__main__":
    main()
