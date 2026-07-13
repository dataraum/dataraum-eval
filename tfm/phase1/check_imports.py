"""Import smoke check for the Phase 1 engine/baseline surface (DAT-743)."""

import importlib

MODULES = [
    "tabpfn_extensions.unsupervised",
    "tabpfn_extensions.interpretability",
    "tabpfn_time_series",
    "tabicl",
    "lightgbm",
    "statsmodels.tsa.exponential_smoothing.ets",
    "sklearn.ensemble",
    "scipy.stats",
]

for name in MODULES:
    try:
        importlib.import_module(name)
        print(f"ok      {name}")
    except Exception as exc:  # noqa: BLE001 — report every failure, keep going
        print(f"FAIL    {name}: {type(exc).__name__}: {exc}")
