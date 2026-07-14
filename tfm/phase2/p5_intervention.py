"""DAT-744 Part 2 — P5: interventional prediction + support boundary.

Substrate: the lever-grid corpora (price_level at k=36 of 48 months; exact
same-seed counterfactuals). Series = monthly activity of the five sales
revenue accounts (41xx/42xx), the lever's direct target.

Leg A — forecast adaptation (in-support transition):
    Context = levered world through month 36+delta (delta in {1, 2, 6}
    levered months visible); predict the next 3 months. Ground truth per
    (account, month): true levered value y_lev AND same-seed counterfactual
    y_base. Recovered effect fraction = (yhat - y_base) / (y_lev - y_base),
    pooled by sums. 1.0 = full effect tracked; 0.0 = model stuck on the
    pre-lever regime. Engines: TabICL + TabPFN-TS (reference) + seasonal
    naive + ETS (classical adaptation reference).

Leg B — what-if support boundary (supervised conditional):
    Rows = (world, account, month>=37): features = lever factor + account +
    pre-lever aggregates (identical across worlds within a seed — the factor
    column is the ONLY between-world signal, the pure what-if shape) + month;
    target = levered-regime activity. Context = support factors
    {0.85..1.20}; queries = held-out 1.10 (in-support interpolation) and
    {0.50, 1.50} (out-of-support). Metrics per query world: effect-recovery
    error, 80% interval width and coverage — honesty = does the interval
    widen out-of-support or does the model extrapolate confidently.

    cd tfm/phase1 && uv run python ../phase2/p5_intervention.py [--leg A|B|both]
    (LGBM baseline for leg B runs in its own process: --leg B-lgbm)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PHASE1 = Path(__file__).resolve().parents[1] / "phase1"
sys.path.insert(0, str(PHASE1))

import baselines as bl  # noqa: E402
import data  # noqa: E402
import engines as eng  # noqa: E402
import results as rs  # noqa: E402

PROBE = "p5_intervention"
SEEDS = (42, 43)
K = 36  # 0-based lever period -> months 37..48 (1-based) are levered
SUPPORT = (0.85, 0.90, 0.95, 1.00, 1.05, 1.15, 1.20)  # 1.00 = baseline corpus
QUERIES = {"in_support_1.10": 1.10, "out_low_0.50": 0.50, "out_high_1.50": 1.50}
LEVELS = eng.QUANTILE_LEVELS


def corpus_name(factor: float, seed: int) -> str:
    return f"p5-base-s{seed}" if factor == 1.0 else f"p5-f{factor:.2f}-s{seed}"


def revenue_series(factor: float, seed: int) -> pd.DataFrame:
    """item_id, timestamp, month_idx (1-based), target — sales revenue accounts only."""
    tb = data.load_table(corpus_name(factor, seed), "trial_balance")
    tb = tb[tb["account_id"].astype(str).str.startswith(("41", "42"))]
    tb = tb[~tb["account_id"].astype(str).str.startswith("43")]
    tb["period"] = pd.PeriodIndex(tb["period"].astype(str), freq="M")
    window = pd.period_range(tb["period"].min(), periods=48, freq="M")
    tb = tb[tb["period"].isin(window)]
    tb["target"] = (tb["credit_balance"] - tb["debit_balance"]).astype(float)  # revenue: credit activity
    grid = pd.MultiIndex.from_product(
        [sorted(tb["account_id"].unique()), window], names=["account_id", "period"]
    )
    out = tb.set_index(["account_id", "period"])["target"].reindex(grid, fill_value=0.0).reset_index()
    out["item_id"] = f"s{seed}/" + out["account_id"].astype(str)
    out["timestamp"] = out["period"].dt.to_timestamp()
    out["month_idx"] = (out["period"] - window[0]).map(lambda x: x.n) + 1
    return out[["item_id", "timestamp", "month_idx", "target"]]


def verify_analytic_effect() -> None:
    """Sanity: levered/baseline revenue ratio == factor for months >= 37."""
    for factor in (1.15, 0.50):
        lev = revenue_series(factor, 42)
        base = revenue_series(1.0, 42)
        m = lev["month_idx"] >= 40  # skip the receipt-lag transition months
        ratio = lev.loc[m, "target"].sum() / base.loc[m, "target"].sum()
        assert abs(ratio - factor) < 0.02, f"factor {factor}: measured {ratio:.4f}"
        pre = lev["month_idx"] <= 36
        assert np.allclose(lev.loc[pre, "target"], base.loc[pre, "target"]), "pre-lever months differ"
    print("[p5] analytic-effect sanity: OK (ratio==factor post-lever, pre-lever identical)")


# ------------------------------------------------------------------- Leg A

def leg_a(engines: list[str]) -> None:
    for factor in (1.15, 1.20, 0.85):
        for seed in SEEDS:
            lev, base = revenue_series(factor, seed), revenue_series(1.0, seed)
            for delta in (1, 2, 6):
                origin = K + delta  # months of context (1-based count)
                ctx = lev[lev["month_idx"] <= origin][["item_id", "timestamp", "target"]]
                fut_mask = (lev["month_idx"] > origin) & (lev["month_idx"] <= origin + 3)
                y_lev = lev[fut_mask].reset_index(drop=True)
                y_base = base[fut_mask.to_numpy()].reset_index(drop=True)
                for name in engines:
                    config = {"factor": factor, "seed": seed, "levered_months_seen": delta}
                    try:
                        with rs.timed() as t:
                            yhat = _point_forecast(name, ctx, y_lev)
                        eff_true = y_lev["target"].sum() - y_base["target"].sum()
                        eff_pred = yhat.sum() - y_base["target"].sum()
                        metrics = {
                            "recovered_effect_frac": round(float(eff_pred / eff_true), 3),
                            "wape_vs_levered_truth": round(
                                float(np.abs(y_lev["target"].to_numpy() - yhat).sum()
                                      / np.abs(y_lev["target"]).sum()), 3),
                            "n": int(len(yhat)),
                        }
                    except Exception as exc:  # a failing engine is a finding
                        rs.record(PROBE, name, config | {"leg": "A"}, {"error": f"{type(exc).__name__}: {exc}"})
                        continue
                    rs.record(PROBE, name, config | {"leg": "A"}, metrics, latency_s=t["s"])


def _point_forecast(name: str, ctx: pd.DataFrame, fut: pd.DataFrame) -> np.ndarray:
    if name in ("tabicl2", "tabpfn3"):
        stub = fut[["item_id", "timestamp"]].copy()
        stub["target"] = np.nan
        pred = eng.ENGINES[name].forecast(ctx, stub, levels=[0.1, 0.5, 0.9])
        pred["timestamp"] = pd.to_datetime(pred["timestamp"])
        cols = {round(float(c), 4): c for c in pred.columns if _is_float(c)}
        merged = fut.merge(pred[["item_id", "timestamp", cols[0.5]]], on=["item_id", "timestamp"],
                           validate="1:1")
        return merged[cols[0.5]].to_numpy(dtype=float)
    rows = []
    for item, g in ctx.groupby("item_id", sort=False):
        hist = g.sort_values("timestamp")["target"].to_numpy()
        h = int((fut["item_id"] == item).sum())
        if name == "seasonal_naive":
            point, _ = bl.seasonal_naive(hist, h, [0.5])
        elif name == "ets":
            point, _ = bl.ets(hist, h, [0.5])
        else:
            raise ValueError(name)
        rows.append(pd.DataFrame({"item_id": item, "h": range(h), "point": point}))
    pred = pd.concat(rows, ignore_index=True)
    fut = fut.copy()
    fut["h"] = fut.groupby("item_id", sort=False).cumcount()
    return fut.merge(pred, on=["item_id", "h"], validate="1:1")["point"].to_numpy(dtype=float)


def _is_float(c: object) -> bool:
    try:
        float(c)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------------- Leg B

def what_if_frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(context_rows, query_rows) for the supervised what-if leg."""
    frames = []
    for factor in (*SUPPORT, *QUERIES.values()):
        for seed in SEEDS:
            s = revenue_series(factor, seed)
            pre = s[s["month_idx"] <= K]
            pre_stats = pre.groupby("item_id")["target"].agg(
                pre_mean="mean", pre_std="std", pre_last="last"
            ).reset_index()
            post = s[s["month_idx"] >= K + 1].merge(pre_stats, on="item_id", validate="m:1")
            post["factor"] = factor
            post["seed"] = seed
            post["month"] = post["timestamp"].dt.month
            post["account_id"] = post["item_id"].str.split("/").str[1]
            frames.append(post)
    df = pd.concat(frames, ignore_index=True)
    is_query = df["factor"].isin(QUERIES.values())
    return df[~is_query].reset_index(drop=True), df[is_query].reset_index(drop=True)


B_FEATURES = ["factor", "account_id", "month", "pre_mean", "pre_std", "pre_last"]


def leg_b(engines: list[str]) -> None:
    ctx, queries = what_if_frame()
    y_ctx = ctx["target"].astype(float)
    base = {seed: revenue_series(1.0, seed) for seed in SEEDS}

    for name in engines:
        for qname, qfactor in QUERIES.items():
            q = queries[queries["factor"] == qfactor].reset_index(drop=True)
            y_true = q["target"].to_numpy(dtype=float)
            y_base = np.concatenate([
                base[seed][(base[seed]["month_idx"] >= K + 1)].sort_values(["item_id", "month_idx"])
                ["target"].to_numpy()
                for seed in SEEDS
            ])
            q_sorted = q.sort_values(["seed", "item_id", "month_idx"]).reset_index(drop=True)
            y_true = q_sorted["target"].to_numpy(dtype=float)
            config = {"leg": "B", "query": qname, "n_ctx": len(ctx), "n_query": len(q)}
            try:
                with rs.timed() as t:
                    if name == "lgbm":
                        qmat = _lgbm_quantiles(ctx[B_FEATURES], y_ctx, q_sorted[B_FEATURES])
                    elif name == "tabfm":
                        point = np.asarray(
                            eng.ENGINES[name].regress(ctx[B_FEATURES], y_ctx, q_sorted[B_FEATURES]),
                            dtype=float)
                        qmat = None
                    else:
                        qmat = eng.ENGINES[name].quantile_regress(
                            ctx[B_FEATURES], y_ctx, q_sorted[B_FEATURES], levels=LEVELS)
                if qmat is not None:
                    point = qmat[LEVELS.index(0.5)]
                eff_true = y_true.sum() - y_base.sum()
                eff_pred = point.sum() - y_base.sum()
                metrics = {
                    "recovered_effect_frac": round(float(eff_pred / eff_true), 3),
                    "wape_vs_truth": round(float(np.abs(y_true - point).sum() / np.abs(y_true).sum()), 3),
                }
                if qmat is not None:
                    lo, hi = qmat[LEVELS.index(0.1)], qmat[LEVELS.index(0.9)]
                    metrics["cover80"] = round(float(np.mean((y_true >= lo) & (y_true <= hi))), 3)
                    metrics["width80_median"] = round(float(np.median(hi - lo)), 1)
            except Exception as exc:  # a failing engine is a finding
                rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                continue
            rs.record(PROBE, name, config, metrics, latency_s=t["s"])


def _lgbm_quantiles(X_tr: pd.DataFrame, y_tr: pd.Series, X_te: pd.DataFrame) -> np.ndarray:
    import lightgbm as lgb

    Xc, Xe = X_tr.copy(), X_te.copy()
    for col in Xc.columns:
        if not pd.api.types.is_numeric_dtype(Xc[col]):
            Xc[col] = Xc[col].astype("category")
            Xe[col] = Xe[col].astype(pd.CategoricalDtype(Xc[col].cat.categories))
    out = []
    for tau in LEVELS:
        m = lgb.LGBMRegressor(objective="quantile", alpha=tau, n_estimators=300,
                              random_state=42, verbose=-1)
        m.fit(Xc, y_tr)
        out.append(m.predict(Xe))
    return np.stack(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", default="both", choices=["A", "B", "B-lgbm", "both"])
    args = ap.parse_args()

    verify_analytic_effect()
    if args.leg in ("A", "both"):
        leg_a(["seasonal_naive", "ets", "tabicl2", "tabpfn3"])
    if args.leg in ("B", "both"):
        leg_b(["tabicl2", "tabpfn3", "tabfm"])
    if args.leg == "B-lgbm":
        leg_b(["lgbm"])
