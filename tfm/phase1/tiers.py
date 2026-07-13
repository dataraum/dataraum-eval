"""DAT-743 scorecard raw material: data efficiency + latency.

Context tiers 100 / 1k / 10k rows on the two supervised tasks (clean
corpus), fixed held-out test set, all three engines + LightGBM. The
literature claims the TFM edge is largest on small contexts — this measures
it, with latency per fit+predict as the cost axis.

Usage: uv run python tiers.py [--smoke] [--engines ...]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

import data
import engines as eng
import results as rs

PROBE = "tiers"
SEED = 42
TIERS = (100, 1000, 10000)
N_TEST = 1500


def lgbm_fit(task: str):
    import lightgbm as lgb

    cls = lgb.LGBMClassifier if task == "classification" else lgb.LGBMRegressor

    def fn(X_tr, y_tr, X_te):
        Xc, Xe = X_tr.copy(), X_te.copy()
        for col in Xc.columns:
            if not pd.api.types.is_numeric_dtype(Xc[col]):
                Xc[col] = Xc[col].astype("category")
                Xe[col] = Xe[col].astype(pd.CategoricalDtype(Xc[col].cat.categories))
        model = cls(n_estimators=300, random_state=SEED, verbose=-1)
        model.fit(Xc, y_tr)
        if task == "classification":
            return model.predict(Xe), model.predict_proba(Xe), model.classes_
        return model.predict(Xe)

    return fn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--engines", default="lgbm,tabicl2,tabpfn3,tabfm")
    args = ap.parse_args()

    tasks = {}
    Xc, yc = data.supervised_classification()
    tasks["classification"] = train_test_split(
        Xc, yc, test_size=min(N_TEST, len(Xc) // 3), random_state=SEED, stratify=yc
    )
    Xr, yr = data.supervised_regression()
    tasks["regression"] = train_test_split(Xr, yr, test_size=N_TEST, random_state=SEED)

    tiers = (100, 500) if args.smoke else TIERS
    for task, (X_tr_all, X_te, y_tr_all, y_te) in tasks.items():
        for tier in tiers:
            if tier > len(X_tr_all):
                continue
            X_tr = X_tr_all.sample(n=tier, random_state=SEED)
            y_tr = y_tr_all.loc[X_tr.index]
            if task == "classification" and y_tr.nunique() < yc.nunique():
                # tiny tiers can miss a class; resample stratified
                X_tr, _, y_tr, _ = train_test_split(
                    X_tr_all, y_tr_all, train_size=tier, random_state=SEED,
                    stratify=y_tr_all,
                )
            for name in args.engines.split(","):
                fn = lgbm_fit(task) if name == "lgbm" else getattr(
                    eng.ENGINES[name],
                    "classify" if task == "classification" else "regress",
                )
                config = {"task": task, "context_rows": tier, "smoke": args.smoke}
                try:
                    with rs.timed() as t:
                        out = fn(X_tr, y_tr, X_te)
                    if task == "classification":
                        labels, proba, classes = out
                        metrics = {
                            "acc": float(accuracy_score(y_te, labels)),
                            "log_loss": float(log_loss(y_te, proba, labels=classes)),
                        }
                    else:
                        pred = np.asarray(out, dtype=float)
                        metrics = {
                            "r2": float(r2_score(y_te, pred)),
                            "mae": float(mean_absolute_error(y_te, pred)),
                        }
                except Exception as exc:  # a failing tier is a finding
                    rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                    continue
                rs.record(PROBE, name, config, metrics, latency_s=t["s"])


if __name__ == "__main__":
    main()
