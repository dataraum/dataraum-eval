"""DAT-757 /ground gate #2 — role provenance for folded dims via disagreement-set tests.

CLAIM UNDER TEST (to refute)
----------------------------
"A near-identical column pair (A, B) can be classified ROLE vs DIRTY-COPY from data
alone — the Markov-blanket idea, operationalized on the only rows that carry any
information: the disagreement set D = {A != B}. Two permutation independence tests:
  T1 (membership):  dis = 1{A!=B}  vs a context column — a ROLE's disagreements are
                    SYSTEMATIC (gift/dropship orders predict bill!=ship); dirt is random.
  T2 (values):      dis vs B — a ROLE's divergent values CONCENTRATE (warehouse/hub
                    cities); dirt's divergent values follow B's marginal.
Role-flag iff min Bonferroni-2 p <= 0.05. Separation must hold at MATCHED disagreement
rates, where every pairwise statistic (pair-g3, row-g3, RFI, perm-p on (A,B)) is
IDENTICAL between the two cases by construction."

Named methods: permutation independence tests (gate #1's perm_pvalue machinery, reused);
the hypotheses framed as conditional structure (Markov blankets differing beyond A~B).

THE ATTACK
----------
Dirty copies at exactly the role pair's disagreement rate are the adversarial control
(false-flag side). Sweep the rate down to the f6-role-dup extreme (a handful of rows) to
map the POWER BOUNDARY k* — below it, the honest verdict is ABSTAIN -> semantic lane
(names/LLM), and that boundary is the deliverable, not a failure.

5 seeds x 5 rates x {role, dirt}. Kill: role-vs-dirt separation fails at realistic
agreement (95-99.5%), i.e. power < 0.8 or false-flag > 0.1 there.

Run:  uv run python scripts/probes/dat757-g3-wide/probe_roles.py   (repo root, ~1 min)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from fdlib import perm_pvalue, scan_pairs  # noqa: E402

N = 20_000
N_CITIES = 120
HUBS = np.arange(5)  # warehouse cities the role's divergent shipments concentrate on
ALPHA = 0.05 / 2  # Bonferroni over the two tests


def build_pair(
    rng: np.random.Generator, rate: float, kind: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(A, B, order_type) with P(A != B) ~= rate.

    kind='role'      : disagreements 100% driven by order_type in {gift, dropship}
                       (15% of rows), divergent values 100% on HUBS — the strongest case.
    kind='role_soft' : only HALF the disagreements systematic, half random — a weaker,
                       more realistic mechanism (the anti-overfit variant).
    kind='dirt'      : disagreement rows uniform-random, values ~ marginal.
    Pairwise, all three are indistinguishable at the same rate by construction.
    """
    a = rng.integers(0, N_CITIES, N)
    order_type = rng.choice(4, N, p=[0.85, 0.06, 0.06, 0.03])  # 0=std 1=gift 2=drop 3=pickup
    b = a.copy()
    k = int(rate * N)
    if kind in ("role", "role_soft"):
        k_sys = k if kind == "role" else k // 2
        eligible = np.flatnonzero((order_type == 1) | (order_type == 2))
        d_sys = rng.choice(eligible, min(len(eligible), k_sys), replace=False)
        b[d_sys] = rng.choice(HUBS, len(d_sys))  # ships from a warehouse hub
        if k - k_sys > 0:  # the non-systematic half (plain noise, like dirt)
            d_rand = rng.choice(N, k - k_sys, replace=False)
            b[d_rand] = rng.integers(0, N_CITIES, k - k_sys)
    else:
        d_idx = rng.choice(N, k, replace=False)
        b[d_idx] = rng.integers(0, N_CITIES, k)  # random re-entry noise ~ marginal
    return a, b, order_type


def role_tests(a: np.ndarray, b: np.ndarray, context: np.ndarray) -> tuple[float, float]:
    """(p_membership, p_values): permutation independence of dis=1{A!=B} vs context / vs B."""
    dis = (a != b).astype(np.int64)
    if dis.sum() == 0:
        return 1.0, 1.0
    df = pl.DataFrame({"dis": dis, "ctx": context, "b": b})
    scan = scan_pairs(df, ["dis", "ctx", "b"])
    return perm_pvalue(scan, "dis", "ctx"), perm_pvalue(scan, "dis", "b")


def main() -> None:
    print(f"# DAT-757 gate #2 — role vs dirty-copy from the disagreement set (n={N})\n")
    rates = [0.0005, 0.001, 0.005, 0.02, 0.05]
    seeds = [11, 22, 33, 44, 55]

    print(f"{'rate':>7} {'~k':>5} | {'role':>6} {'p_med':>9} | {'role_soft':>9} {'p_med':>9} "
          f"| {'dirt (false-flag)':>17}")
    boundary = {"role": None, "role_soft": None}
    for rate in rates:
        flags = {"role": 0, "role_soft": 0, "dirt": 0}
        p_med: dict[str, list[float]] = {"role": [], "role_soft": []}
        for kind in ("role", "role_soft", "dirt"):
            for seed in seeds:
                rng = np.random.default_rng(seed)
                a, b, ctx = build_pair(rng, rate, kind)
                p1, p2 = role_tests(a, b, ctx)
                if kind != "dirt":
                    p_med[kind].append(min(p1, p2))
                flags[kind] += min(p1, p2) <= ALPHA
        for kind in ("role", "role_soft"):
            if flags[kind] / len(seeds) >= 0.8 and flags["dirt"] / len(seeds) <= 0.1 \
                    and boundary[kind] is None:
                boundary[kind] = rate
        print(f"{rate:>7.2%} {int(rate * N):>5} | {flags['role']}/5 {np.median(p_med['role']):>9.1e} "
              f"| {flags['role_soft']:>5}/5 {np.median(p_med['role_soft']):>9.1e} "
              f"| {flags['dirt']}/5")

    print("\n## the f6-role-dup extreme (k=2) — threshold-boundary zone, expect ABSTAIN")
    print("   (with 2 rows the membership p CANNOT go below ~0.15^2=0.0225 — any decision")
    print("    there is alpha-sensitive; the honest rule is a minimum-k floor -> abstain)")
    rng = np.random.default_rng(99)
    a, b, ctx = build_pair(rng, 2 / N, "role")
    p1, p2 = role_tests(a, b, ctx)
    print(f"  k=2 role: p1={p1:.3f} p2={p2:.3f} (floor ~0.0225 vs alpha {ALPHA}) -> ABSTAIN by k-floor")

    print("\n## VERDICT")
    for kind, label in (("role", "strong mechanism"), ("role_soft", "half-systematic")):
        b_ = boundary[kind]
        print(f"  {label:16}: separation from rate ~{b_:.2%} (~k={int(b_ * N)})" if b_ is not None
              else f"  {label:16}: no separating rate found")
    print("  Pairwise stats are blind at ALL these rates by construction — the disagreement")
    print("  set carries the role signal. Below the k-floor: ABSTAIN -> concept/name lane.")


if __name__ == "__main__":
    main()
