"""DAT-459 PROBE — lens: noisy-stock.

ATTACK: the constructed STOCK (clean cumsum of per-period net) is idealized. Real
balance-sheet series carry prior-period RESTATEMENTS, audit ADJUSTMENTS, posting
MEASUREMENT NOISE, and occasional partial RESETS (year-end close). The claim is that
rho1 (->1) and VR (->0) cleanly+robustly separate stock from flow at T~12 with no
tuning. We perturb the stock BEFORE measuring and find how much noise it takes before
rho1 leaves the stock band / the paired AUC vs flow falls below 0.9.

We reuse load_series / rho1 / var_ratio / _auc verbatim from the spike script.

Perturbations (applied per-account to STOCK_bal, with fixed RNG seed for reproducibility):
  (a) additive measurement noise:  y += N(0, frac * std(y))   for frac in {0.01,0.05,0.10,0.20,0.50}
  (b) restatement jumps:  replace k randomly-chosen periods' values with a revised value
      = original * (1 + jump),  jump ~ +-25%, for k in {1,2,3}
  (c) partial reset: one interior period's value is pulled toward 0 (year-end close),
      y[t] *= reset_frac, for reset_frac in {0.5, 0.1, 0.0}
  (d) COMBINED realistic stress: 5% measurement noise + 2 restatement jumps + a 50% reset.

For each scenario we report:
  - median rho1 / VR of the perturbed stock across accounts
  - fraction of accounts whose rho1 stays in the "stock band" (rho1 >= 0.5; a generous
    midpoint between flow~0 and stock~1)
  - paired rank AUC of perturbed-stock rho1 vs each flow's rho1 (want >= 0.9 to "hold")
  - paired rank AUC of perturbed-stock VR vs flow VR, ON THE STOCK SIDE (stock VR LOW,
    so we compute AUC(flow_VR > stock_VR); want >= 0.9 to "hold")

Breakdown threshold = the lowest noise level at which the rho1 AUC vs the *hardest*
flow drops below 0.9, OR median rho1 drops below 0.5.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dat459_stock_flow_signature import _auc, load_series, rho1, var_ratio  # noqa: E402

DATA = Path("data/clean")
MIN_T = 6
SEED = 459
RHO1_STOCK_BAND = 0.5  # midpoint between flow(~0) and stock(~1)
HOLD = 0.90  # AUC threshold for "separator still holds"

FLOWS = ["TB_debit", "TB_net", "GL_debit"]


def add_measurement_noise(y: np.ndarray, frac: float, rng: np.random.Generator) -> np.ndarray:
    s = np.std(y)
    if s == 0:
        return y.copy()
    return y + rng.normal(0.0, frac * s, size=len(y))


def add_restatements(y: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    y = y.copy()
    T = len(y)
    if T < 3:
        return y
    idx = rng.choice(T, size=min(k, T), replace=False)
    for i in idx:
        jump = rng.uniform(-0.25, 0.25)
        y[i] = y[i] * (1.0 + jump)
    return y


def partial_reset(y: np.ndarray, reset_frac: float, rng: np.random.Generator) -> np.ndarray:
    """Pull one interior period toward zero (year-end close), then carry forward.

    A real partial reset doesn't just dent one period — the balance is drawn down and
    the SUBSEQUENT levels start from the reset point. We model the honest version: pick
    an interior period, scale it AND shift everything after it by the same delta so the
    series stays a genuine running balance with a step-down. This is the most adversarial
    (and most realistic) form: a true structural break in the level."""
    y = y.copy()
    T = len(y)
    if T < 4:
        return y
    t = int(rng.integers(1, T - 1))  # interior
    new_val = y[t] * reset_frac
    delta = new_val - y[t]
    y[t:] = y[t:] + delta
    return y


def measure(stock_by_acct: dict[str, np.ndarray], flows: dict[str, dict[str, np.ndarray]]):
    """Return (rho1 stats, VR stats, paired AUCs) for a perturbed-stock dict."""
    accts = list(stock_by_acct.keys())
    s_rho = np.array([rho1(stock_by_acct[a]) for a in accts], dtype=float)
    s_vr = np.array([var_ratio(stock_by_acct[a]) for a in accts], dtype=float)

    rho_med = np.nanmedian(s_rho)
    vr_med = np.nanmedian(s_vr)
    in_band = np.nanmean(s_rho >= RHO1_STOCK_BAND)

    rho_aucs, vr_aucs = {}, {}
    for f in FLOWS:
        f_rho = np.array([rho1(flows[a][f]) for a in accts], dtype=float)
        f_vr = np.array([var_ratio(flows[a][f]) for a in accts], dtype=float)
        # stock rho1 should be HIGHER than flow rho1
        rho_aucs[f] = _auc(s_rho, f_rho)
        # stock VR should be LOWER than flow VR -> AUC(flow_vr > stock_vr)
        vr_aucs[f] = _auc(f_vr, s_vr)
    return rho_med, vr_med, in_band, rho_aucs, vr_aucs


def fmt_aucs(d: dict[str, float]) -> str:
    return "  ".join(f"{k}={v:.3f}" for k, v in d.items())


def worst(d: dict[str, float]) -> float:
    return min(d.values())


def main() -> None:
    rng = np.random.default_rng(SEED)
    series = load_series()
    kept = {a: s for a, s in series.items() if len(s["TB_net"]) >= MIN_T}
    flows = {a: {f: kept[a][f] for f in FLOWS} for a in kept}
    clean_stock = {a: kept[a]["STOCK_bal"] for a in kept}

    print(f"DATA={DATA}  kept(T>={MIN_T})={len(kept)}  seed={SEED}")
    print(f"rho1 stock-band threshold = {RHO1_STOCK_BAND}; AUC hold threshold = {HOLD}\n")

    # baseline (clean constructed stock)
    rho_med, vr_med, in_band, rho_aucs, vr_aucs = measure(clean_stock, flows)
    print("=== BASELINE: clean constructed stock ===")
    print(f"  rho1 median={rho_med:.3f}  in-band={in_band:.2f}  VR median={vr_med:.4f}")
    print(f"  rho1 AUC vs flows: {fmt_aucs(rho_aucs)}  (worst={worst(rho_aucs):.3f})")
    print(f"  VR   AUC vs flows: {fmt_aucs(vr_aucs)}  (worst={worst(vr_aucs):.3f})")
    print()

    breakdowns: list[str] = []

    def run_scenario(label: str, make_stock):
        # fresh rng per scenario so scenarios are independent + reproducible
        local_rng = np.random.default_rng(abs(hash(label)) % (2**32))
        pert = {a: make_stock(clean_stock[a], local_rng) for a in kept}
        rho_med, vr_med, in_band, rho_aucs, vr_aucs = measure(pert, flows)
        wr, wv = worst(rho_aucs), worst(vr_aucs)
        held = (rho_med >= RHO1_STOCK_BAND) and (wr >= HOLD)
        flag = "HOLD " if held else "BREAK"
        print(f"[{flag}] {label}")
        print(f"        rho1 med={rho_med:+.3f}  in-band={in_band:.2f}  VR med={vr_med:.4f}")
        print(f"        rho1 AUC worst={wr:.3f} ({fmt_aucs(rho_aucs)})")
        print(f"        VR   AUC worst={wv:.3f} ({fmt_aucs(vr_aucs)})")
        if not held:
            breakdowns.append(label)
        return held

    print("=== (a) additive measurement noise (frac of series std) ===")
    for frac in [0.01, 0.05, 0.10, 0.20, 0.50]:
        run_scenario(
            f"meas-noise {int(frac*100):>2d}%",
            lambda y, r, frac=frac: add_measurement_noise(y, frac, r),
        )
    print()

    print("=== (b) restatement jumps (k periods revised +-25%) ===")
    for k in [1, 2, 3]:
        run_scenario(f"restatements k={k}", lambda y, r, k=k: add_restatements(y, k, r))
    print()

    print("=== (c) partial reset (one interior period -> reset_frac, carried forward) ===")
    for rf in [0.5, 0.1, 0.0]:
        run_scenario(
            f"partial-reset frac={rf}",
            lambda y, r, rf=rf: partial_reset(y, rf, r),
        )
    print()

    print("=== (d) COMBINED realistic stress (5% noise + 2 restatements + 50% reset) ===")
    def combined(y, r):
        y = add_measurement_noise(y, 0.05, r)
        y = add_restatements(y, 2, r)
        y = partial_reset(y, 0.5, r)
        return y
    run_scenario("combined 5%+k2+reset0.5", combined)
    print()

    # also: heavier combined stress to find where even realistic-but-bad data breaks it
    print("=== (e) HEAVY combined stress (10% noise + 3 restatements + full reset to 0) ===")
    def heavy(y, r):
        y = add_measurement_noise(y, 0.10, r)
        y = add_restatements(y, 3, r)
        y = partial_reset(y, 0.0, r)
        return y
    run_scenario("heavy 10%+k3+reset0.0", heavy)
    print()

    # ── ADVERSARIAL reset patterns: the carry-forward step is the *gentle* version. ──
    # A real year-end close can produce (i) a one-period DIP that does NOT carry forward
    # (balance drawn to ~0 at close, then rebuilt) and (ii) repeated quarterly sawtooth
    # closes. Both destroy the monotone-ish autocorrelation far more than a single step.
    def dip_no_carry(y, r, frac):
        """One interior period dips toward frac*level; subsequent periods UNCHANGED
        (a transient close, not a structural step). Creates a sharp spike-down."""
        y = y.copy()
        T = len(y)
        if T < 4:
            return y
        t = int(r.integers(1, T - 1))
        y[t] = y[t] * frac
        return y

    def sawtooth(y, r, period, frac):
        """Every `period`-th interior point dips toward frac*level (quarterly closes),
        no carry-forward. Multiple transient draw-downs."""
        y = y.copy()
        T = len(y)
        for t in range(period, T, period):
            y[t] = y[t] * frac
        return y

    print("=== (f) ADVERSARIAL year-end close: one-period DIP, no carry-forward ===")
    for frac in [0.5, 0.1, 0.0]:
        run_scenario(f"dip-no-carry frac={frac}", lambda y, r, frac=frac: dip_no_carry(y, r, frac))
    print()

    print("=== (g) ADVERSARIAL sawtooth: quarterly closes (every 3rd period -> frac) ===")
    for frac in [0.5, 0.1, 0.0]:
        run_scenario(f"sawtooth q=3 frac={frac}", lambda y, r, frac=frac: sawtooth(y, r, 3, frac))
    print()

    # ── per-account dispersion at the worst HELD edge: medians hide tail failures. ──
    print("=== (h) per-account rho1 dispersion under heavy combined (medians hide tails) ===")
    local_rng = np.random.default_rng(abs(hash("heavy-dispersion")) % (2**32))
    pert = {a: heavy(clean_stock[a], local_rng) for a in kept}
    s_rho = np.array([rho1(pert[a]) for a in kept], dtype=float)
    s_rho = s_rho[~np.isnan(s_rho)]
    print(f"        rho1  min={np.min(s_rho):+.3f}  p05={np.percentile(s_rho,5):+.3f}  "
          f"med={np.median(s_rho):+.3f}  frac<0.5={np.mean(s_rho<0.5):.2f}  frac<0={np.mean(s_rho<0):.2f}")
    print()

    print("=== VERDICT SUMMARY ===")
    if not breakdowns:
        print("  No scenario broke the separator (rho1 stayed in band AND AUC>=0.9 vs all flows).")
    else:
        print(f"  {len(breakdowns)} scenario(s) broke it: {breakdowns}")


if __name__ == "__main__":
    main()
