"""DAT-742 Phase 0: TabPFN toy run on the shaped corpus (device=mps).

Tries TabPFN-3 first (gated weights — browser license acceptance / TABPFN_TOKEN);
falls back to TabPFN-2 (Apache-2.0, ungated) so the MPS plumbing is proven even
if auth is pending. Both outcomes are inventory findings.
"""

import numpy as np
from common import Inventory, clf_split, reg_split
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, r2_score
from tabpfn import TabPFNClassifier, TabPFNRegressor
from tabpfn.constants import ModelVersion

DEVICE = "mps"
inv = Inventory("tabpfn")

Xc_tr, Xc_te, yc_tr, yc_te = clf_split()
Xr_tr, Xr_te, yr_tr, yr_te = reg_split()

version_used: ModelVersion | None = None
for version in (ModelVersion.V3, ModelVersion.V2):

    def classify(version: ModelVersion = version) -> str:
        clf = TabPFNClassifier.create_default_for_version(version, device=DEVICE)
        clf.fit(Xc_tr, yc_tr)
        acc = accuracy_score(yc_te, clf.predict(Xc_te))
        ll = log_loss(yc_te, clf.predict_proba(Xc_te), labels=clf.classes_)
        return f"{version.value}: acc={acc:.3f} log_loss={ll:.3f} ({len(Xc_tr)} train rows)"

    inv.run("classification", classify)
    if inv.rows[-1]["status"] == "ok":
        version_used = version
        break

if version_used is None:
    inv.missing("regression", "no model version loadable — see classification errors")
    inv.missing("quantiles", "no model version loadable")
else:

    def regress() -> str:
        reg = TabPFNRegressor.create_default_for_version(version_used, device=DEVICE)
        reg.fit(Xr_tr, yr_tr)
        pred = reg.predict(Xr_te)
        return (
            f"{version_used.value}: r2={r2_score(yr_te, pred):.3f} "
            f"mae={mean_absolute_error(yr_te, pred):.0f} ({len(Xr_tr)} train rows)"
        )

    def quantiles() -> str:
        reg = TabPFNRegressor.create_default_for_version(version_used, device=DEVICE)
        reg.fit(Xr_tr, yr_tr)
        qs = reg.predict(Xr_te, output_type="quantiles", quantiles=[0.1, 0.5, 0.9])
        arr = np.asarray(qs)
        cover = np.mean((yr_te.to_numpy() >= arr[0]) & (yr_te.to_numpy() <= arr[2]))
        return f"{version_used.value}: native quantile output; empirical 80% coverage={cover:.2f}"

    inv.run("regression", regress)
    inv.run("quantiles", quantiles)

inv.missing("forecast", "not in core tabpfn; separate tabpfn-time-series package")
inv.missing("anomaly", "not in core tabpfn; tabpfn-extensions unsupervised (outlier detection)")
inv.missing("imputation", "not in core tabpfn; tabpfn-extensions unsupervised")
inv.missing("feature_importance", "not in core tabpfn; tabpfn-extensions (SHAP)")

inv.save()
