"""DAT-743 Phase 1: uniform engine adapters (device=mps).

One class per engine; every read-out an engine exposes gets one method with a
harness-normalized contract, so probes iterate engines without special cases:

    classify(X_tr, y_tr, X_te)            -> (labels, proba, classes)
    regress(X_tr, y_tr, X_te)             -> point ndarray
    quantile_regress(X_tr, y_tr, X_te, L) -> ndarray (len(L), n_te)
    forecast(context_df, future_df, L)    -> long df: item_id, timestamp, q{tau}...
    anomaly_scores(X_df)                  -> ndarray, HIGHER = more anomalous
    impute(X_df with NaNs)                -> DataFrame, same shape
    feature_importance(X_df, y, task)     -> {feature: mean |SHAP|}

A missing read-out raises NotImplementedError — the probe records the gap
(design doc: gaps are results, not workarounds). TabFM regression feeds
float32 y (upstream MPS bug, google-research/tabfm#68).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEVICE = "mps"
SEED = 42
# 80% interval = (0.1, 0.9); 95% = (0.025, 0.975); median for point.
QUANTILE_LEVELS = [0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975]


def encode_for_density(
    X: pd.DataFrame,
) -> tuple[np.ndarray, list[int], dict[str, pd.Index]]:
    """Ordinal-encode object columns -> float32 matrix, categorical indices,
    and the per-column category vocabularies (for decoding back).

    Shared by the density/imputation read-outs whose engines take bare
    matrices (TabPFN unsupervised wants explicit categorical indices;
    TabICL infers them). NaNs pass through.
    """
    out = np.empty(X.shape, dtype=np.float32)
    cat_idx: list[int] = []
    vocab: dict[str, pd.Index] = {}
    for j, col in enumerate(X.columns):
        s = X[col]
        if pd.api.types.is_numeric_dtype(s):
            out[:, j] = s.astype(np.float32)
        else:
            cat_idx.append(j)
            cat = s.astype("category")
            vocab[col] = cat.cat.categories
            codes = cat.cat.codes.to_numpy().astype(np.float32)
            codes[codes == -1] = np.nan  # cat.codes uses -1 for NaN
            out[:, j] = codes
    # corrupt_type injects float64-max-scale tokens that overflow float32 to
    # inf and fail sklearn validation — treat non-finite as missing (the NaN
    # itself remains an anomaly trace)
    out[~np.isfinite(out)] = np.nan
    return out, cat_idx, vocab


def decode_from_density(
    matrix: np.ndarray, template: pd.DataFrame, vocab: dict[str, pd.Index]
) -> pd.DataFrame:
    """Inverse of encode_for_density: imputed codes -> original categories
    (rounded + clipped to the vocabulary), numerics passed through."""
    out = pd.DataFrame(np.asarray(matrix, dtype=float), columns=template.columns,
                       index=template.index)
    for col, cats in vocab.items():
        codes = out[col].round().clip(0, len(cats) - 1)
        decoded = pd.Series(pd.NA, index=out.index, dtype=object)
        ok = codes.notna()
        decoded[ok] = cats[codes[ok].astype(int)]
        out[col] = decoded
    return out


def _quantile_matrix(raw: object, levels: list[float], n: int) -> np.ndarray:
    """Normalize an engine's quantile output to shape (len(levels), n)."""
    arr = np.asarray(raw, dtype=float)
    if arr.shape == (len(levels), n):
        return arr
    if arr.shape == (n, len(levels)):
        return arr.T
    raise ValueError(f"unexpected quantile shape {arr.shape} for L={len(levels)} n={n}")


def _shap_to_importance(values: np.ndarray, feature_names: list[str]) -> dict[str, float]:
    """mean |SHAP| per feature; multiclass third axis averaged out."""
    v = np.abs(np.asarray(values, dtype=float))
    while v.ndim > 2:
        v = v.mean(axis=-1)
    return dict(zip(feature_names, v.mean(axis=0)))


# ---------------------------------------------------------------- TabPFN

class TabPFN:
    name = "tabpfn3"

    def _clf(self):
        from tabpfn import TabPFNClassifier
        from tabpfn.constants import ModelVersion

        return TabPFNClassifier.create_default_for_version(ModelVersion.V3, device=DEVICE)

    def _reg(self):
        from tabpfn import TabPFNRegressor
        from tabpfn.constants import ModelVersion

        return TabPFNRegressor.create_default_for_version(ModelVersion.V3, device=DEVICE)

    def classify(self, X_tr, y_tr, X_te):
        clf = self._clf()
        clf.fit(X_tr, y_tr)
        return clf.predict(X_te), clf.predict_proba(X_te), clf.classes_

    def regress(self, X_tr, y_tr, X_te):
        reg = self._reg()
        reg.fit(X_tr, y_tr)
        return reg.predict(X_te)

    def quantile_regress(self, X_tr, y_tr, X_te, levels=QUANTILE_LEVELS):
        reg = self._reg()
        reg.fit(X_tr, y_tr)
        qs = reg.predict(X_te, output_type="quantiles", quantiles=list(levels))
        return _quantile_matrix(qs, levels, len(X_te))

    def forecast(self, context_df, future_df, levels=QUANTILE_LEVELS):
        """context/future: item_id, timestamp, target(+covariates). Long output."""
        from tabpfn_time_series import TabPFNTSPipeline

        pipe = TabPFNTSPipeline()  # LOCAL mode; routes tensors to mps itself
        pred = pipe.predict_df(
            context_df, future_df=future_df, quantiles=list(levels)
        )
        return pred.reset_index()

    def anomaly_scores(self, X: pd.DataFrame, n_permutations: int = 5):
        from tabpfn_extensions.unsupervised import TabPFNUnsupervisedModel

        Xn, cat_idx, _vocab = encode_for_density(X)
        model = TabPFNUnsupervisedModel(tabpfn_clf=self._clf(), tabpfn_reg=self._reg())
        model.set_categorical_features(cat_idx)
        model.fit(Xn)
        log_density = model.outliers(Xn, n_permutations=n_permutations)
        return -np.asarray(log_density.cpu(), dtype=float)  # low density = anomalous

    def impute(self, X: pd.DataFrame):
        from tabpfn_extensions.unsupervised import TabPFNUnsupervisedModel

        import torch

        Xn, cat_idx, vocab = encode_for_density(X)
        model = TabPFNUnsupervisedModel(tabpfn_clf=self._clf(), tabpfn_reg=self._reg())
        model.set_categorical_features(cat_idx)
        model.fit(Xn)
        filled = model.impute(torch.tensor(Xn))
        return decode_from_density(np.asarray(filled.cpu()), X, vocab)

    def feature_importance(self, X: pd.DataFrame, y, task: str):
        """Mean |SHAP| via the shap package's permutation explainer over the
        fitted TabPFN predictor (the tabpfn-extensions documented route)."""
        import shap

        # shap does float arithmetic on the input — feed the ordinal-encoded
        # matrix (TabPFN takes NaN codes natively; importance is per column)
        Xn, _, _vocab = encode_for_density(X)
        Xn = pd.DataFrame(Xn, columns=X.columns)
        model = self._clf() if task == "classification" else self._reg()
        model.fit(Xn, y)
        fn = model.predict_proba if task == "classification" else model.predict
        explainer = shap.PermutationExplainer(fn, Xn, seed=SEED)
        # each explained row costs O(features) full-context predicts — bound it
        explain = Xn.sample(n=min(200, len(Xn)), random_state=SEED)
        sv = explainer(explain)
        return _shap_to_importance(sv.values, list(X.columns))


# ---------------------------------------------------------------- TabICL

class TabICL:
    name = "tabicl2"

    def classify(self, X_tr, y_tr, X_te):
        from tabicl import TabICLClassifier

        clf = TabICLClassifier(device=DEVICE)
        clf.fit(X_tr, y_tr)
        return clf.predict(X_te), clf.predict_proba(X_te), clf.classes_

    def regress(self, X_tr, y_tr, X_te):
        from tabicl import TabICLRegressor

        reg = TabICLRegressor(device=DEVICE)
        reg.fit(X_tr, y_tr)
        return reg.predict(X_te)

    def quantile_regress(self, X_tr, y_tr, X_te, levels=QUANTILE_LEVELS):
        from tabicl import TabICLRegressor

        reg = TabICLRegressor(device=DEVICE)
        reg.fit(X_tr, y_tr)
        qs = reg.predict(X_te, output_type="quantiles", alphas=list(levels))
        return _quantile_matrix(qs, levels, len(X_te))

    def forecast(self, context_df, future_df, levels=QUANTILE_LEVELS):
        from tabicl.forecast import TabICLForecaster

        forecaster = TabICLForecaster(tabicl_config={"device": DEVICE})
        pred = forecaster.predict_df(
            context_df, future_df=future_df, quantiles=list(levels)
        )
        return pred.reset_index()

    def anomaly_scores(self, X: pd.DataFrame, n_permutations: int = 4):
        from tabicl import TabICLUnsupervised

        Xn, _, _vocab = encode_for_density(X)
        uns = TabICLUnsupervised(device=DEVICE)
        uns.fit(Xn)
        return -uns.score_samples(Xn, n_permutations=n_permutations)

    def impute(self, X: pd.DataFrame):
        from tabicl import TabICLUnsupervised

        Xn, _, vocab = encode_for_density(X)
        uns = TabICLUnsupervised(device=DEVICE)
        uns.fit(Xn)
        filled = uns.impute(Xn)
        return decode_from_density(np.asarray(filled), X, vocab)

    def feature_importance(self, X: pd.DataFrame, y, task: str):
        from tabicl import TabICLClassifier, TabICLRegressor
        from tabicl.shap import get_shap_values

        model = (
            TabICLClassifier(device=DEVICE)
            if task == "classification"
            else TabICLRegressor(device=DEVICE)
        )
        # tabicl.shap casts the matrix to float — feed ordinal codes
        Xn, _, _vocab = encode_for_density(X)
        model.fit(Xn, y)
        sv = get_shap_values(model, Xn, attribute_names=list(X.columns))
        return _shap_to_importance(sv.values, list(X.columns))


# ---------------------------------------------------------------- TabFM

class TabFM:
    name = "tabfm"

    def _load(self, model_type: str):
        from tabfm import tabfm_v1_0_0_pytorch

        return tabfm_v1_0_0_pytorch.load(model_type=model_type, device=DEVICE)

    def classify(self, X_tr, y_tr, X_te):
        from tabfm import TabFMClassifier

        clf = TabFMClassifier(model=self._load("classification"))
        clf.fit(X_tr, y_tr)
        return clf.predict(X_te), clf.predict_proba(X_te), clf.classes_

    def regress(self, X_tr, y_tr, X_te):
        from tabfm import TabFMRegressor

        reg = TabFMRegressor(model=self._load("regression"))
        # float32: TabFM moves y to mps before its own float64 guard (tabfm#68)
        reg.fit(X_tr, np.asarray(y_tr, dtype=np.float32))
        return reg.predict(X_te)


ENGINES = {"tabpfn3": TabPFN(), "tabicl2": TabICL(), "tabfm": TabFM()}
