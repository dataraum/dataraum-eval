"""DAT-742 Phase 0: TabICL v2 toy run on the shaped corpus (device=mps).

Probes the full read-out surface: classifier, regressor (mean + quantiles),
forecaster (monthly account series), and TabICLUnsupervised (density-based
anomaly scoring + imputation). Checkpoints auto-download from HF Hub.
"""

import numpy as np
import pandas as pd
from common import SEED, Inventory, clf_split, load_series, reg_split
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, r2_score
from tabicl import TabICLClassifier, TabICLRegressor, TabICLUnsupervised

DEVICE = "mps"
inv = Inventory("tabicl")

Xc_tr, Xc_te, yc_tr, yc_te = clf_split()
Xr_tr, Xr_te, yr_tr, yr_te = reg_split()


def classify() -> str:
    clf = TabICLClassifier(device=DEVICE)
    clf.fit(Xc_tr, yc_tr)
    acc = accuracy_score(yc_te, clf.predict(Xc_te))
    ll = log_loss(yc_te, clf.predict_proba(Xc_te), labels=clf.classes_)
    return f"v2 ckpt: acc={acc:.3f} log_loss={ll:.3f} ({len(Xc_tr)} train rows)"


reg = TabICLRegressor(device=DEVICE)


def regress() -> str:
    reg.fit(Xr_tr, yr_tr)
    pred = reg.predict(Xr_te)
    return (
        f"v2 ckpt: r2={r2_score(yr_te, pred):.3f} "
        f"mae={mean_absolute_error(yr_te, pred):.0f} ({len(Xr_tr)} train rows)"
    )


def quantiles() -> str:
    qs = reg.predict(Xr_te, output_type="quantiles", alphas=[0.1, 0.5, 0.9])
    cover = np.mean((yr_te.to_numpy() >= qs[:, 0]) & (yr_te.to_numpy() <= qs[:, 2]))
    return f"native quantile output via alphas; empirical 80% coverage={cover:.2f}"


def forecast() -> str:
    from tabicl import TabICLForecaster

    series = load_series()
    df = series.rename(
        columns={"account_id": "item_id", "period": "timestamp", "net_balance": "target"}
    )[["item_id", "timestamp", "target"]]
    horizon = 3
    context = df.groupby("item_id", group_keys=False).apply(lambda g: g.iloc[:-horizon])
    fc = TabICLForecaster(tabicl_config={"device": DEVICE})
    pred = fc.predict_df(context, prediction_length=horizon, quantiles=[0.1, 0.5, 0.9])
    n_series = df["item_id"].nunique()
    return f"series-as-table forecast: {n_series} account series, horizon {horizon}, quantile bands; {len(pred)} rows out"


def anomaly() -> str:
    X = Xr_tr.select_dtypes(include=[np.number]).to_numpy()[:1000]
    uns = TabICLUnsupervised(device=DEVICE)
    uns.fit(X)
    scores = uns.score_samples(X[:200])
    return f"log-density score_samples on {X.shape}: mean={np.mean(scores):.2f} (density-based anomaly read-out)"


def imputation() -> str:
    X = Xr_tr.select_dtypes(include=[np.number]).to_numpy()[:500].copy()
    rng = np.random.default_rng(SEED)
    mask = rng.random(X.shape) < 0.1
    X_missing = X.copy()
    X_missing[mask] = np.nan
    uns = TabICLUnsupervised(device=DEVICE)
    uns.fit(X_missing)
    X_imp = uns.impute(X_missing)
    err = np.nanmean(np.abs(X_imp[mask] - X[mask]))
    return f"native impute() on 10% masked cells: mae={err:.1f}"


def feature_importance() -> str:
    import tabicl.shap  # noqa: F401 — presence check; SHAP runs are Phase 1 material

    return "tabicl.shap module present (SHAP via all-NaN column masking); not exercised in toy run"


inv.run("classification", classify)
inv.run("regression", regress)
inv.run("quantiles", quantiles)
inv.run("forecast", forecast)
inv.run("anomaly", anomaly)
inv.run("imputation", imputation)
inv.run("feature_importance", feature_importance)

inv.save()
