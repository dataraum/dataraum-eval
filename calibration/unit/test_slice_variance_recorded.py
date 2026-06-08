"""Tier-1 FINDING: why slice_variance was cut (DAT-442 reset).

slice_variance tried to flag "this column behaves differently across slices."
The grounded form of that question is a between-slice k-sample test — Kruskal–
Wallis H with the η² effect size. We asked whether moving to that grounded
statistic would rescue the detector. It does not, for two STRUCTURAL reasons,
both proven synthetically below and confirmed on the real recorded data:

1. **A between-slice test is blind to slice-GLOBAL injections.** Every injection
   the eval creates (outliers, formula drift, round numbers) is sprayed
   uniformly across all slices, so it raises every group's distribution equally
   and leaves the *between-group* η² unchanged (Δη² ≈ 0). On the real data:
   journal_lines.credit / debit / net_amount grouped by cost_center gave
   η² = 0.000 on BOTH clean and injected — Δ = 0.000.

2. **Where slices genuinely differ, it's legitimate business structure, not
   corruption.** A grounded k-sample test then saturates on clean data with no
   headroom to separate an injection. On the real data: bank_transactions.amount
   grouped by counterparty gave clean η² = 0.776, injected 0.739 (Δ = −0.036).

No grounded statistic rescues a measure whose target the injections never create
and whose signal, when present, is real heterogeneity. slice_variance was cut.
(The one defensible sliver — null-rate-across-slices — is a proportions question,
Cramér's V on null×slice, deferred to DAT-184 + a slice-conditional-null
injection. It is NOT what Kruskal–Wallis measures.)

This test flips — signalling "reconsider" — only if a future slice-conditional
injection makes injected η² separate from clean by more than the margin.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import kruskal  # type: ignore[import-untyped]

_SEPARATION_MARGIN = 0.05  # what "measurably above the clean baseline" would require
_SATURATION_FLOOR = 0.5  # naturally-heterogeneous slices already clear this


def _eta_sq(groups: list[np.ndarray]) -> float:
    """η² effect size from Kruskal–Wallis H: (H − k + 1) / (n − k), clamped [0,1].

    The grounded between-slice k-sample magnitude — the statistic the cut was
    tested against. Self-contained so the finding outlives the (deleted) detector.
    """
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or n - k <= 0:
        return 0.0
    h = float(kruskal(*groups).statistic)
    return max(0.0, min((h - k + 1) / (n - k), 1.0))


def _spray_global_injection(slices: list[np.ndarray]) -> list[np.ndarray]:
    """A slice-GLOBAL corruption: 5% ×10 outliers added to EVERY slice equally —
    exactly the shape of the eval's injections (uniform over the column, blind to
    which slice a row lands in)."""
    out = []
    for s in slices:
        a = s.copy()
        a[: len(a) // 20] *= 10.0
        out.append(a)
    return out


def test_slice_global_injection_is_invisible_to_k_sample() -> None:
    """Mechanism 1: a uniform-across-slices injection leaves between-group η² ≈ 0.

    Mirrors the real result (credit/debit/net by cost_center: Δη² = 0.000).
    """
    rng = np.random.default_rng(0)
    # 5 slices drawn iid from ONE shared distribution → homogeneous, η² ≈ 0.
    clean = [rng.normal(100.0, 15.0, 200) for _ in range(5)]
    injected = _spray_global_injection(clean)

    eta_clean = _eta_sq(clean)
    eta_injected = _eta_sq(injected)
    print(f"global-injection: clean η²={eta_clean:.3f} injected η²={eta_injected:.3f}")
    assert eta_injected <= eta_clean + _SEPARATION_MARGIN, (
        f"slice-global injection separated (Δ={eta_injected - eta_clean:+.3f}) — "
        "a between-slice test would have recall; reconsider the cut."
    )


def test_natural_heterogeneity_saturates_with_no_headroom() -> None:
    """Mechanism 2: genuinely different slices already saturate η², and a uniform
    injection on top still doesn't separate.

    Mirrors the real result (amount by counterparty: clean 0.776, injected 0.739).
    """
    rng = np.random.default_rng(1)
    # 5 slices with genuinely different centres — legitimate business structure.
    hetero = [rng.normal(mu, 15.0, 200) for mu in (50.0, 100.0, 150.0, 200.0, 250.0)]
    eta_clean = _eta_sq(hetero)
    eta_injected = _eta_sq(_spray_global_injection(hetero))
    print(f"natural-heterogeneity: clean η²={eta_clean:.3f} injected η²={eta_injected:.3f}")

    assert eta_clean >= _SATURATION_FLOOR, (
        f"clean η²={eta_clean:.3f} below saturation floor — synthetic slices not "
        "heterogeneous enough to model the real failure mode."
    )
    assert eta_injected <= eta_clean + _SEPARATION_MARGIN, (
        f"injection separated on heterogeneous slices (Δ={eta_injected - eta_clean:+.3f})."
    )
