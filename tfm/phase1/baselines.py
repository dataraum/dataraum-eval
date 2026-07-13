"""DAT-743 Phase 1: classical baselines.

Forecast baselines (P1/P4) all emit the same shape as the TFM adapters:
(point, {tau: quantile_pred}) per horizon step, so the metrics module treats
engines and baselines identically.

- seasonal naive: y-hat(t+h) = y(t+h-m); quantiles = point + empirical
  residual quantiles of the same rule on the history (classical benchmark
  method, cf. Hyndman & Athanasopoulos FPP).
- ETS: statsmodels ETSModel (additive error/trend/season), predictive
  quantiles from 1000 simulated sample paths (simulation-based intervals).
- LightGBM quantile: pooled ("global") model over all series, direct
  multi-horizon strategy — one model per (quantile, horizon) with lag +
  calendar features; the standard gradient-boosting quantile setup (M5).

P3: IsolationForest. P6: kNN / mean-mode imputers (sklearn).
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


# ------------------------------------------------------------ seasonal naive

def seasonal_naive(
    history: np.ndarray, horizon: int, levels: list[float], season: int = 12
) -> tuple[np.ndarray, dict[float, np.ndarray]]:
    y = np.asarray(history, dtype=float)
    m = season if len(y) > season else 1
    point = np.array([y[len(y) - m + (h % m)] for h in range(horizon)])
    # residuals of the naive rule, one-step, over the history
    resid = y[m:] - y[:-m] if len(y) > m else np.zeros(1)
    qs = {tau: point + np.quantile(resid, tau) for tau in levels}
    return point, qs


# ---------------------------------------------------------------------- ETS

def ets(
    history: np.ndarray,
    horizon: int,
    levels: list[float],
    season: int = 12,
    n_paths: int = 1000,
    seed: int = 42,
) -> tuple[np.ndarray, dict[float, np.ndarray]]:
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    y = pd.Series(np.asarray(history, dtype=float))
    seasonal = "add" if len(y) >= 2 * season + 1 else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ETSModel(
            y,
            error="add",
            trend="add",
            seasonal=seasonal,
            seasonal_periods=season if seasonal else None,
        )
        fit = model.fit(disp=False)
        paths = fit.simulate(
            nsimulations=horizon,
            repetitions=n_paths,
            anchor="end",
            random_state=np.random.RandomState(seed),
        )
    sims = np.asarray(paths)  # (horizon, n_paths)
    point = sims.mean(axis=1)
    qs = {tau: np.quantile(sims, tau, axis=1) for tau in levels}
    return point, qs


# ------------------------------------------------------------ LightGBM quantile

LAGS = (1, 2, 3, 6, 12)


def _lgbm_features(df: pd.DataFrame) -> pd.DataFrame:
    """df: columns item_id, timestamp, target — long format, monthly."""
    out = df.sort_values(["item_id", "timestamp"]).copy()
    g = out.groupby("item_id")["target"]
    for lag in LAGS:
        out[f"lag_{lag}"] = g.shift(lag)
    out["roll_mean_3"] = g.shift(1).rolling(3).mean().reset_index(level=0, drop=True)
    out["roll_mean_12"] = g.shift(1).rolling(12).mean().reset_index(level=0, drop=True)
    out["month"] = out["timestamp"].dt.month
    out["item_id"] = out["item_id"].astype("category")
    return out


def lgbm_quantile_forecast(
    context_df: pd.DataFrame,
    horizon: int,
    levels: list[float],
    seed: int = 42,
) -> pd.DataFrame:
    """Direct multi-horizon pooled quantile GBM.

    context_df: item_id, timestamp, target (monthly). Returns long frame
    item_id, h, plus one column per tau ("q{tau}") and "point" (the median).
    """
    import lightgbm as lgb

    feats = _lgbm_features(context_df)
    feat_cols = [c for c in feats.columns if c not in ("timestamp", "target")]
    rows = []
    for h in range(1, horizon + 1):
        feats[f"y_h{h}"] = feats.groupby("item_id")["target"].shift(-h)
        train = feats.dropna(subset=[f"y_h{h}", f"lag_{max(LAGS)}"])
        # forecast origin: the last observed timestamp per item
        origin = feats.groupby("item_id", observed=True).tail(1)
        preds: dict[float, np.ndarray] = {}
        for tau in levels:
            model = lgb.LGBMRegressor(
                objective="quantile",
                alpha=tau,
                n_estimators=300,
                learning_rate=0.05,
                min_child_samples=10,
                random_state=seed,
                verbose=-1,
            )
            model.fit(train[feat_cols], train[f"y_h{h}"], categorical_feature=["item_id"])
            preds[tau] = model.predict(origin[feat_cols])
        for i, item in enumerate(origin["item_id"].to_numpy()):
            row: dict[str, object] = {"item_id": item, "h": h}
            for tau in levels:
                row[f"q{tau}"] = float(preds[tau][i])
            row["point"] = row[f"q{0.5}"] if 0.5 in levels else float(np.median([row[f"q{t}"] for t in levels]))
            rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ P3 / P6

def isolation_forest_scores(X: pd.DataFrame, seed: int = 42) -> np.ndarray:
    """Higher = more anomalous (negated sklearn score_samples)."""
    from sklearn.ensemble import IsolationForest

    Xn = pd.get_dummies(X, dummy_na=True)
    forest = IsolationForest(n_estimators=300, random_state=seed)
    forest.fit(Xn)
    return -forest.score_samples(Xn)


def knn_impute_numeric(X_num: pd.DataFrame, n_neighbors: int = 5) -> pd.DataFrame:
    from sklearn.impute import KNNImputer

    imp = KNNImputer(n_neighbors=n_neighbors)
    return pd.DataFrame(imp.fit_transform(X_num), columns=X_num.columns, index=X_num.index)


def mean_mode_impute(X: pd.DataFrame) -> pd.DataFrame:
    out = X.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = out[col].fillna(out[col].mean())
        else:
            mode = out[col].mode(dropna=True)
            out[col] = out[col].fillna(mode.iloc[0] if not mode.empty else "missing")
    return out
