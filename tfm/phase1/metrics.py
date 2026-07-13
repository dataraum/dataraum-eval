"""DAT-743 Phase 1: probe metrics — every one a named, established method.

Forecast: WAPE; CRPS via the quantile-averaged pinball loss (the standard
K-quantile CRPS approximation, as in the M5 uncertainty track / GluonTS
weighted quantile loss); central-interval empirical coverage; reliability
curve (nominal quantile level vs empirical P(y <= q_tau)).
Structure: Spearman rho / Kendall tau rank agreement.
Anomaly: AUROC / average precision / precision-recall at a labeled budget.
Imputation: normalized RMSE (numeric), accuracy (categorical).
"""

from __future__ import annotations

import numpy as np
from scipy import stats as sps
from sklearn.metrics import average_precision_score, roc_auc_score


# ---------------------------------------------------------------- forecast

def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.abs(y_true).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(y_true - y_pred).sum() / denom)


def pinball(y_true: np.ndarray, q_pred: np.ndarray, tau: float) -> float:
    y_true = np.asarray(y_true, dtype=float)
    q_pred = np.asarray(q_pred, dtype=float)
    diff = y_true - q_pred
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def crps_quantile(
    y_true: np.ndarray, levels: list[float], q_preds: np.ndarray
) -> float:
    """CRPS approximated as 2 * mean pinball loss over the quantile grid.

    ``q_preds`` has shape (len(levels), n_obs). Exact CRPS is the integral of
    the pinball loss over tau in (0,1); averaging over a fixed grid is the
    standard discretization.
    """
    q_preds = np.asarray(q_preds, dtype=float)
    losses = [pinball(y_true, q_preds[i], tau) for i, tau in enumerate(levels)]
    return float(2.0 * np.mean(losses))


def interval_coverage(
    y_true: np.ndarray, lo: np.ndarray, hi: np.ndarray
) -> float:
    y_true = np.asarray(y_true, dtype=float)
    return float(np.mean((y_true >= np.asarray(lo)) & (y_true <= np.asarray(hi))))


def reliability_curve(
    y_true: np.ndarray, levels: list[float], q_preds: np.ndarray
) -> dict[float, float]:
    """Nominal level tau -> empirical P(y <= q_tau). Calibrated: identity."""
    y_true = np.asarray(y_true, dtype=float)
    q_preds = np.asarray(q_preds, dtype=float)
    return {
        tau: float(np.mean(y_true <= q_preds[i])) for i, tau in enumerate(levels)
    }


# ---------------------------------------------------------------- structure

def rank_agreement(
    truth_scores: dict[str, float], model_scores: dict[str, float]
) -> dict[str, float]:
    """Spearman rho + Kendall tau over the features present in both rankings."""
    keys = sorted(set(truth_scores) & set(model_scores))
    if len(keys) < 3:
        return {"spearman": float("nan"), "kendall": float("nan"), "n_features": len(keys)}
    t = [truth_scores[k] for k in keys]
    m = [model_scores[k] for k in keys]
    rho = sps.spearmanr(t, m)
    tau = sps.kendalltau(t, m)
    return {
        "spearman": float(rho.statistic),
        "kendall": float(tau.statistic),
        "n_features": len(keys),
    }


# ---------------------------------------------------------------- anomaly

def anomaly_metrics(labels: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    """Label-ranking metrics for anomaly scores (higher score = more anomalous).

    Precision/recall are reported at the labeled budget (top-k with k = #positives,
    the "R-precision" operating point) — threshold-free, so no tuned cutoffs.
    """
    labels = np.asarray(labels, dtype=int)
    scores = np.asarray(scores, dtype=float)
    n_pos = int(labels.sum())
    out: dict[str, float] = {"n": int(labels.size), "n_pos": n_pos}
    if n_pos == 0 or n_pos == labels.size:
        return out | {"auroc": float("nan"), "ap": float("nan"), "p_at_budget": float("nan")}
    out["auroc"] = float(roc_auc_score(labels, scores))
    out["ap"] = float(average_precision_score(labels, scores))
    top = np.argsort(-scores)[:n_pos]
    out["p_at_budget"] = float(labels[top].mean())  # == recall@budget when k = n_pos
    return out


# ---------------------------------------------------------------- imputation

def imputation_error(
    true_vals: np.ndarray, imputed_vals: np.ndarray, kind: str
) -> dict[str, float]:
    """numeric -> NRMSE (RMSE / std of true values); categorical -> accuracy."""
    if kind == "numeric":
        t = np.asarray(true_vals, dtype=float)
        p = np.asarray(imputed_vals, dtype=float)
        sd = float(np.std(t))
        rmse = float(np.sqrt(np.mean((t - p) ** 2)))
        return {"nrmse": rmse / sd if sd > 0 else float("nan"), "n_cells": int(t.size)}
    acc = float(np.mean(np.asarray(true_vals) == np.asarray(imputed_vals)))
    return {"accuracy": acc, "n_cells": int(len(true_vals))}
