"""DAT-743 addendum: split-conformal (CQR) calibration of the P1 quantiles.

Method: Conformalized Quantile Regression (Romano, Patterson, Candes 2019).
For a nominal interval [q_lo, q_hi] with miscoverage alpha, the conformity
score on a held-out calibration set is E_i = max(q_lo_i - y_i, y_i - q_hi_i);
the calibrated interval widens both ends by the (1-alpha)(1+1/n) empirical
quantile of E. Distribution-free coverage guarantee under exchangeability.

Design: calibrate on origins {36, 39}, evaluate on origins {42, 45} —
a temporal split, so exchangeability holds only approximately (the standard
rolling-conformal caveat); the measured post-coverage is the honest answer.

Reads output/phase1/p1_preds/{engine}_o{origin}.parquet (from
`p1_forecast.py --dump`); records to the p1_conformal results file.

    uv run python p1_conformal.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import results as rs

PROBE = "p1_conformal"
CAL_ORIGINS = (36, 39)
EVAL_ORIGINS = (42, 45)
INTERVALS = {"80": (0.1, 0.9, 0.2), "95": (0.025, 0.975, 0.05)}
ENGINES = ("tabpfn3", "tabicl2")


def load(engine: str, origins: tuple[int, ...]) -> pd.DataFrame:
    frames = [
        pd.read_parquet(rs.RESULTS_DIR / "p1_preds" / f"{engine}_o{o}.parquet")
        for o in origins
    ]
    return pd.concat(frames, ignore_index=True)


def cqr(cal: pd.DataFrame, ev: pd.DataFrame, lo: float, hi: float, alpha: float) -> dict:
    y_cal = cal["target"].to_numpy(dtype=float)
    scores = np.maximum(
        cal[str(lo)].to_numpy(dtype=float) - y_cal,
        y_cal - cal[str(hi)].to_numpy(dtype=float),
    )
    n = len(scores)
    level = min(1.0, (1 - alpha) * (1 + 1 / n))
    c = float(np.quantile(scores, level))

    y = ev["target"].to_numpy(dtype=float)
    lo_raw = ev[str(lo)].to_numpy(dtype=float)
    hi_raw = ev[str(hi)].to_numpy(dtype=float)
    pre = float(np.mean((y >= lo_raw) & (y <= hi_raw)))
    post = float(np.mean((y >= lo_raw - c) & (y <= hi_raw + c)))
    width_pre = float(np.median(hi_raw - lo_raw))
    width_post = float(np.median((hi_raw + c) - (lo_raw - c)))
    return {
        "cover_pre": round(pre, 3),
        "cover_post": round(post, 3),
        "correction": round(c, 1),
        "width_median_pre": round(width_pre, 1),
        "width_median_post": round(width_post, 1),
        "width_ratio": round(width_post / width_pre, 3),
        "n_cal": n,
        "n_eval": int(len(y)),
    }


def main() -> None:
    for engine in ENGINES:
        cal, ev = load(engine, CAL_ORIGINS), load(engine, EVAL_ORIGINS)
        for name, (lo, hi, alpha) in INTERVALS.items():
            metrics = cqr(cal, ev, lo, hi, alpha)
            rs.record(
                PROBE, engine,
                {"interval": name, "cal_origins": list(CAL_ORIGINS),
                 "eval_origins": list(EVAL_ORIGINS)},
                metrics,
            )


if __name__ == "__main__":
    main()
