"""DAT-743 P4: conditional prediction on exogenous covariates.

Supervised framing (all three engines expose regression): predict monthly
account activity from autoregressive base features, then add conditioning
blocks and measure the lift:

    base          lags 1-3 + rolling mean/std + account_id (NO calendar)
    base+calendar + month-of-year  -> constructed signal EXISTS
                    (q4_seasonal_boost=0.3, generators.py:303)
    base+fx       + monthly fx means -> NEGATIVE CONTROL: the DGP has no
                    fx->amount coupling (ground_truth.FX_IS_COUPLED=False);
                    any "lift" here is noise-fitting.

Temporal split: test = last 9 months of each seeded history (contains one
full Q4), train = everything earlier. Metrics: WAPE + MAE per feature set,
relative lift vs base, and the per-month mean residual (bias) profile —
with the calendar block the Q4 bias should collapse toward zero
(correctness of the conditional response, not just error lift).

Usage: uv run python p4_conditioning.py [--smoke] [--engines ...]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import data
import engines as eng
import metrics as mx
import results as rs

PROBE = "p4_conditioning"
SEED = 42
TEST_MONTHS = 9

FEATURE_SETS = {
    "base": data.P4_BASE,
    "base+calendar": data.P4_BASE + data.P4_CALENDAR,
    "base+fx": data.P4_BASE + data.P4_FX,
    "base+calendar+fx": data.P4_BASE + data.P4_CALENDAR + data.P4_FX,
}


def lgbm_regress(X_tr, y_tr, X_te):
    import lightgbm as lgb

    Xc, Xe = X_tr.copy(), X_te.copy()
    for col in Xc.columns:
        if not pd.api.types.is_numeric_dtype(Xc[col]):
            Xc[col] = Xc[col].astype("category")
            Xe[col] = Xe[col].astype("category")
    model = lgb.LGBMRegressor(n_estimators=300, random_state=SEED, verbose=-1)
    model.fit(Xc, y_tr)
    return model.predict(Xe)


def monthly_bias(frame: pd.DataFrame, pred: np.ndarray) -> dict[str, float]:
    resid = pred - frame["target"].to_numpy(dtype=float)
    by_month = pd.Series(resid).groupby(frame["month"].to_numpy()).mean()
    return {str(m): round(float(v), 1) for m, v in by_month.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--engines", default="lgbm,tabicl2,tabpfn3,tabfm")
    args = ap.parse_args()

    frame = data.p4_supervised()
    cutoff = frame["timestamp"].max() - pd.DateOffset(months=TEST_MONTHS - 1)
    train, test = frame[frame["timestamp"] < cutoff], frame[frame["timestamp"] >= cutoff]
    n_ctx = 400 if args.smoke else 3000
    if len(train) > n_ctx:
        train = train.sample(n=n_ctx, random_state=SEED)
    if args.smoke:
        test = test.sample(n=150, random_state=SEED)

    y_tr = train["target"].astype(float)
    y_te = test["target"].to_numpy(dtype=float)

    for name in args.engines.split(","):
        fn = lgbm_regress if name == "lgbm" else eng.ENGINES[name].regress
        base_wape = None
        for set_name, cols in FEATURE_SETS.items():
            config = {"feature_set": set_name, "n_train": len(train),
                      "n_test": len(test), "smoke": args.smoke}
            try:
                with rs.timed() as t:
                    pred = np.asarray(fn(train[cols], y_tr, test[cols]), dtype=float)
                metrics = {
                    "wape": mx.wape(y_te, pred),
                    "mae": float(np.mean(np.abs(y_te - pred))),
                    "bias_by_month": monthly_bias(test, pred),
                }
                if set_name == "base":
                    base_wape = metrics["wape"]
                elif base_wape:
                    metrics["lift_vs_base"] = round((base_wape - metrics["wape"]) / base_wape, 4)
            except Exception as exc:  # a failing engine is a finding
                rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                continue
            rs.record(PROBE, name, config, metrics, latency_s=t["s"])


if __name__ == "__main__":
    main()
