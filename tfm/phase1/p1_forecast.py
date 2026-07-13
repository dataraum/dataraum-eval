"""DAT-743 P1: probabilistic forecasting — monthly account activity, h=1-3.

Rolling-origin evaluation on the 48-month clean corpora (135 series =
27 accounts x 5 seeds): origins {36, 39, 42, 45}, horizon 3, quantile grid
QUANTILE_LEVELS. Engines: TabPFN-TS, TabICL forecaster (TabFM: no forecast
read-out — recorded gap, not scored). Baselines: seasonal naive, ETS,
pooled LightGBM quantile (direct multi-horizon).

Metrics per (engine, origin), pooled over items and horizons: WAPE (median
as point), CRPS (quantile-averaged pinball), 80/95% coverage, reliability
curve; plus per-horizon WAPE/CRPS.

Usage: uv run python p1_forecast.py [--smoke] [--engines tabpfn3,tabicl2,...]
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

ORIGINS = (36, 39, 42, 45)
LEVELS = eng.QUANTILE_LEVELS
PROBE = "p1_forecast"


def _quantile_cols(pred: pd.DataFrame) -> dict[float, str]:
    """Map requested tau -> prediction column (engines name them '0.1' etc.)."""
    out: dict[float, str] = {}
    for col in pred.columns:
        try:
            out[round(float(col), 4)] = col
        except (TypeError, ValueError):
            continue
    missing = [t for t in LEVELS if round(t, 4) not in out]
    if missing:
        raise ValueError(f"prediction lacks quantile columns {missing}; has {list(pred.columns)}")
    return out


def score(fut: pd.DataFrame, pred: pd.DataFrame) -> dict:
    """Align actuals with quantile predictions and compute the P1 metrics."""
    cols = _quantile_cols(pred)
    # engines echo a 'target' column in their output — keep only keys + quantiles
    pred = pred[["item_id", "timestamp", *dict.fromkeys(cols.values())]]
    merged = fut.merge(pred, on=["item_id", "timestamp"], how="left", validate="1:1")
    if merged[cols[0.5]].isna().any():
        n = int(merged[cols[0.5]].isna().sum())
        raise ValueError(f"{n} future rows missing predictions")
    merged["h"] = merged.groupby("item_id", sort=False).cumcount() + 1

    y = merged["target"].to_numpy(dtype=float)
    q = np.stack([merged[cols[round(t, 4)]].to_numpy(dtype=float) for t in LEVELS])
    out = {
        "wape": mx.wape(y, q[LEVELS.index(0.5)]),
        "crps": mx.crps_quantile(y, LEVELS, q),
        "cover80": mx.interval_coverage(y, q[LEVELS.index(0.1)], q[LEVELS.index(0.9)]),
        "cover95": mx.interval_coverage(y, q[LEVELS.index(0.025)], q[LEVELS.index(0.975)]),
        "reliability": {str(k): round(v, 4) for k, v in mx.reliability_curve(y, LEVELS, q).items()},
        "n": int(len(y)),
    }
    for h in (1, 2, 3):
        m = (merged["h"] == h).to_numpy()
        out[f"wape_h{h}"] = mx.wape(y[m], q[LEVELS.index(0.5)][m])
        out[f"crps_h{h}"] = mx.crps_quantile(y[m], LEVELS, q[:, m])
    return out


def run_tfm(engine_name: str, ctx: pd.DataFrame, fut: pd.DataFrame) -> pd.DataFrame:
    engine = eng.ENGINES[engine_name]
    future_stub = fut[["item_id", "timestamp"]].copy()
    future_stub["target"] = np.nan  # both predict_df paths require the column present
    pred = engine.forecast(ctx, future_stub, levels=LEVELS)
    pred["item_id"] = pred["item_id"].astype(str)
    pred["timestamp"] = pd.to_datetime(pred["timestamp"])
    return pred


def run_seasonal_naive(ctx: pd.DataFrame, fut: pd.DataFrame) -> pd.DataFrame:
    return _per_item(ctx, fut, lambda hist, h: bl.seasonal_naive(hist, h, LEVELS))


def run_ets(ctx: pd.DataFrame, fut: pd.DataFrame) -> pd.DataFrame:
    return _per_item(ctx, fut, lambda hist, h: bl.ets(hist, h, LEVELS))


def _per_item(ctx, fut, fn) -> pd.DataFrame:
    rows = []
    for item, g in ctx.groupby("item_id", sort=False):
        g = g.sort_values("timestamp")
        f = fut[fut["item_id"] == item].sort_values("timestamp")
        _, qs = fn(g["target"].to_numpy(), len(f))
        for i, ts in enumerate(f["timestamp"].to_numpy()):
            row = {"item_id": item, "timestamp": ts}
            for tau in LEVELS:
                row[str(tau)] = qs[tau][i]
            rows.append(row)
    return pd.DataFrame(rows)


def run_lgbm(ctx: pd.DataFrame, fut: pd.DataFrame) -> pd.DataFrame:
    pred = bl.lgbm_quantile_forecast(ctx, horizon=3, levels=LEVELS)
    # map (item, h) -> future timestamp
    fut = fut.sort_values(["item_id", "timestamp"]).copy()
    fut["h"] = fut.groupby("item_id", sort=False).cumcount() + 1
    merged = fut[["item_id", "timestamp", "h"]].merge(pred, on=["item_id", "h"], validate="1:1")
    return merged.rename(columns={f"q{t}": str(t) for t in LEVELS})


RUNNERS = {
    "tabpfn3": lambda c, f: run_tfm("tabpfn3", c, f),
    "tabicl2": lambda c, f: run_tfm("tabicl2", c, f),
    "seasonal_naive": run_seasonal_naive,
    "ets": run_ets,
    "lgbm_quantile": run_lgbm,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    # NB: never mix lgbm_quantile with the torch engines in ONE process —
    # lightgbm's libomp and torch's OpenMP clash and abort the process.
    ap.add_argument("--engines", default=",".join(RUNNERS))
    ap.add_argument("--origins", default=None, help="comma list, e.g. 39,42,45")
    args = ap.parse_args()

    series = data.monthly_series()
    origins = (36,) if args.smoke else ORIGINS
    if args.origins:
        origins = tuple(int(o) for o in args.origins.split(","))
    if args.smoke:
        keep = series["item_id"].drop_duplicates().sample(12, random_state=42)
        series = series[series["item_id"].isin(keep)]

    for origin in origins:
        ctx, fut = data.split_origin(series, origin)
        for name in args.engines.split(","):
            config = {"origin": origin, "n_items": ctx["item_id"].nunique(),
                      "smoke": args.smoke}
            try:
                with rs.timed() as t:
                    pred = RUNNERS[name](ctx, fut.copy())
                metrics = score(fut, pred)
            except Exception as exc:  # a failing engine is a finding, not an abort
                rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                continue
            rs.record(PROBE, name, config, metrics, latency_s=t["s"])


if __name__ == "__main__":
    main()
