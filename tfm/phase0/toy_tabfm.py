"""DAT-742 Phase 0: Google TabFM toy run on the shaped corpus (PyTorch backend).

TabFM documents classification/regression only — the other read-outs are recorded
as missing, which is itself a Phase 0 result. Loader is a plain ``.to(device)``,
so we try mps (bfloat16 default) and record whatever happens; weights download
from HF Hub (google/tabfm-1.0.0-pytorch).
"""

from common import Inventory, clf_split, reg_split
from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score
from tabfm import TabFMClassifier, TabFMRegressor, tabfm_v1_0_0_pytorch

DEVICE = "mps"
inv = Inventory("tabfm")

Xc_tr, Xc_te, yc_tr, yc_te = clf_split()
Xr_tr, Xr_te, yr_tr, yr_te = reg_split()


def load_model(model_type: str):
    """Load on mps/bf16; fall back to fp32 then cpu, recording the working combo."""
    attempts = [(DEVICE, "bf16-default"), (DEVICE, "fp32"), ("cpu", "bf16-default")]
    errors = []
    for device, dtype_tag in attempts:
        try:
            if dtype_tag == "fp32":
                model = tabfm_v1_0_0_pytorch.load(model_type, device=device, dtype=None)
            else:
                model = tabfm_v1_0_0_pytorch.load(model_type, device=device)
            return model, f"{device}/{dtype_tag}"
        except Exception as e:  # noqa: BLE001 — fallback chain, last error re-raised below
            errors.append(f"{device}/{dtype_tag}: {type(e).__name__}: {e}")
    raise RuntimeError(" | ".join(errors))


def classify() -> str:
    model, combo = load_model("classification")
    clf = TabFMClassifier(model=model)
    clf.fit(Xc_tr, yc_tr)
    acc = accuracy_score(yc_te, clf.predict(Xc_te))
    return f"v1.0.0 pytorch on {combo}: acc={acc:.3f} ({len(Xc_tr)} train rows)"


def regress() -> str:
    model, combo = load_model("regression")
    reg = TabFMRegressor(model=model)
    reg.fit(Xr_tr, yr_tr)
    pred = reg.predict(Xr_te)
    return (
        f"v1.0.0 pytorch on {combo}: r2={r2_score(yr_te, pred):.3f} "
        f"mae={mean_absolute_error(yr_te, pred):.0f} ({len(Xr_tr)} train rows)"
    )


inv.run("classification", classify)
inv.run("regression", regress)

inv.missing("quantiles", "not exposed — point predictions only")
inv.missing("forecast", "not exposed")
inv.missing("anomaly", "not exposed")
inv.missing("imputation", "not exposed")
inv.missing("feature_importance", "not exposed")

inv.save()
