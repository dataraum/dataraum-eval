"""DAT-743 P2: structure recovery — feature importance vs the constructed DGP.

Two targets with exact DGP formulas (ground_truth.py):
    net_amount    = debit - credit                      (row-level, exact)
    debit_balance = sum_debit (recomputed per DGP rule) (aggregate identity)

Engines expose SHAP-based importance (TabPFN via shap PermutationExplainer,
TabICL via tabicl.shap); baseline = LightGBM gain importance. TabFM has no
importance read-out — recorded gap.

Metrics: Spearman/Kendall rank agreement of mean |importance| against
formula membership (1.0 in-formula / 0.0 out), plus top_k_exact — whether
the |formula| top-ranked features are exactly the formula features. The
ranking includes injected pure-noise columns, so a sane model must place
them at the bottom.

Usage: uv run python p2_importance.py [--smoke] [--engines ...]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import data
import engines as eng
import ground_truth as gt
import metrics as mx
import results as rs

PROBE = "p2_importance"
SEED = 42


def lgbm_importance(X: pd.DataFrame, y: pd.Series, task: str) -> dict[str, float]:
    import lightgbm as lgb

    Xc = X.copy()
    for col in Xc.columns:
        if not pd.api.types.is_numeric_dtype(Xc[col]):
            Xc[col] = Xc[col].astype("category")
    model = lgb.LGBMRegressor(n_estimators=300, random_state=SEED, verbose=-1,
                              importance_type="gain")
    model.fit(Xc, y)
    return dict(zip(X.columns, model.feature_importances_.astype(float)))


def evaluate(importance: dict[str, float], formula: dict[str, float],
             all_features: list[str]) -> dict:
    truth = {f: formula.get(f, 0.0) for f in all_features}
    agree = mx.rank_agreement(truth, importance)
    k = sum(1 for v in truth.values() if v > 0)
    top_k = sorted(importance, key=importance.get, reverse=True)[:k]
    agree["top_k_exact"] = sorted(top_k) == sorted(f for f, v in truth.items() if v > 0)
    agree["ranking"] = {f: round(float(v), 5) for f, v in
                        sorted(importance.items(), key=lambda kv: -kv[1])}
    return agree


TARGETS = {
    "net_amount": (data.p2_net_amount, gt.NET_AMOUNT_FORMULA),
    "tb_debit_balance": (lambda: data.p2_tb_balance(side="debit"), gt.TB_DEBIT_FORMULA),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--engines", default="lgbm,tabicl2,tabpfn3")
    args = ap.parse_args()

    n_fit = 300 if args.smoke else 1500  # in-context rows the explainers see

    for target, (builder, formula) in TARGETS.items():
        X, y = builder()
        if len(X) > n_fit:
            idx = X.sample(n=n_fit, random_state=SEED).index
            X, y = X.loc[idx].reset_index(drop=True), y.loc[idx].reset_index(drop=True)
        for name in args.engines.split(","):
            config = {"target": target, "n": len(X), "smoke": args.smoke}
            try:
                with rs.timed() as t:
                    if name == "lgbm":
                        imp = lgbm_importance(X, y, "regression")
                    else:
                        imp = eng.ENGINES[name].feature_importance(X, y, "regression")
                metrics = evaluate(imp, formula, list(X.columns))
            except Exception as exc:  # a failing read-out is a finding
                rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                continue
            rs.record(PROBE, name, config, metrics, latency_s=t["s"])


if __name__ == "__main__":
    main()
