"""Tier-1/2: the DAT-473 slice-conditional-null kill-gate result, pinned.

The catalog records BUILD for slice-conditional nulls: bias-corrected Cramér's V
(Bergsma) on the 2xK is-null x slice table under the Cochran validity rule
(any expected cell < 5 -> abstain) separates the family (1-2 affected slices
holding >= 10% of rows, conditional rate 0.2-0.6 vs base <= 0.05) from MCAR
missingness on the recorded fixture's real dimension shapes by a margin
(probe 2026-06-11: family min 0.129 vs adversary max 0.063).

This test pins that separation so the eventual engine implementation has a
reference statistic and the gate result cannot silently rot. The probe that
produced it is deleted (CLAUDE.md: probes die once the verdict is recorded);
this file IS the verdict's executable form.
"""

from __future__ import annotations

import json
import math
import random

from calibration.unit.fixture import load_fixture

COCHRAN_MIN_EXPECTED = 5.0  # standard chi^2 validity rule


def cramers_v(is_null: list[bool], slices: list[str]) -> float | None:
    """Bias-corrected Cramér's V (Bergsma); None = abstain (Cochran/degenerate)."""
    n = len(is_null)
    cats = sorted(set(slices))
    if n == 0 or len(cats) < 2:
        return None
    obs: dict[tuple[bool, str], int] = {}
    row_tot = {True: 0, False: 0}
    col_tot = dict.fromkeys(cats, 0)
    for flag, cat in zip(is_null, slices, strict=True):
        obs[(flag, cat)] = obs.get((flag, cat), 0) + 1
        row_tot[flag] += 1
        col_tot[cat] += 1
    if row_tot[True] == 0 or row_tot[False] == 0:
        return None
    chi2 = 0.0
    for flag in (True, False):
        for cat in cats:
            expected = row_tot[flag] * col_tot[cat] / n
            if expected < COCHRAN_MIN_EXPECTED:
                return None
            chi2 += (obs.get((flag, cat), 0) - expected) ** 2 / expected
    phi2 = chi2 / n
    r, k = 2, len(cats)
    phi2c = max(0.0, phi2 - (r - 1) * (k - 1) / (n - 1))
    rc = r - (r - 1) ** 2 / (n - 1)
    kc = k - (k - 1) ** 2 / (n - 1)
    denom = min(rc - 1, kc - 1)
    return math.sqrt(phi2c / denom) if denom > 0 else None


def _real_dims() -> dict[str, list[str]]:
    """The fixture's real categorical shapes (nulls dropped)."""
    conn = load_fixture()
    out: dict[str, list[str]] = {}
    for source, col in (
        ("journal_lines", "cost_center"),
        ("invoices", "status"),
        ("payments", "method"),
    ):
        vals = [
            json.loads(r[0]).get(col)
            for r in conn.execute(
                "SELECT row_json FROM raw_values WHERE strategy='clean' AND source=?",
                (source,),
            )
        ]
        out[f"{source}.{col}"] = [str(v) for v in vals if v not in (None, "")]
    conn.close()
    return out


def _mcar(rng: random.Random, n: int, rate: float) -> list[bool]:
    return [rng.random() < rate for _ in range(n)]


def _family_instance(rng: random.Random, dims: list[str]) -> list[bool] | None:
    """One family draw: 1-2 affected slices with >= 10% combined row mass."""
    counts: dict[str, int] = {}
    for d in dims:
        counts[d] = counts.get(d, 0) + 1
    cats = sorted(counts)
    for _ in range(50):
        affected = set(rng.sample(cats, rng.choice((1, 2))))
        if sum(counts[c] for c in affected) / len(dims) >= 0.10:
            cond = rng.uniform(0.2, 0.6)
            base = rng.uniform(0.0, 0.05)
            return [rng.random() < (cond if d in affected else base) for d in dims]
    return None


def test_family_separates_from_mcar_on_real_dim_shapes() -> None:
    """Family min must exceed the MCAR adversary max by the gate's margin class."""
    rng = random.Random(4473)
    dims_by_name = _real_dims()

    adversary: list[float] = []
    family: list[float] = []
    for dims in dims_by_name.values():
        for rate in (0.05, 0.40):
            for _ in range(15):
                v = cramers_v(_mcar(rng, len(dims), rate), dims)
                if v is not None:
                    adversary.append(v)
        for _ in range(40):
            flags = _family_instance(rng, dims)
            if flags is None:
                continue
            v = cramers_v(flags, dims)
            if v is not None:
                family.append(v)

    assert adversary and family
    # Ordering with a margin — the kill-gate criterion, not a tuned point.
    assert min(family) > max(adversary), (
        f"separation lost: family min {min(family):.4f} <= adversary max {max(adversary):.4f}"
    )
    assert max(adversary) < 0.1, f"MCAR adversary drifted high: {max(adversary):.4f}"


def test_cochran_rule_absorbs_small_slice_inflation() -> None:
    """The v1 failure mode — n=300, K=12 tiny skewed slices under MCAR — must
    abstain (invalid table), never report an inflated association."""
    rng = random.Random(4473)
    cats = [f"S{i:02d}" for i in range(12)]
    weights = [10.0 if i < 2 else 0.3 for i in range(12)]
    total = sum(weights)
    cum, acc = [], 0.0
    for w in weights:
        acc += w / total
        cum.append(acc)

    for _ in range(30):
        dims = []
        for _ in range(300):
            u = rng.random()
            dims.append(cats[next(i for i, c in enumerate(cum) if u <= c)])
        assert cramers_v(_mcar(rng, 300, 0.05), dims) is None


def test_abstains_on_degenerate_tables() -> None:
    """K=1 dims, all-null and no-null columns are undefined — abstain, not 0-vs-1."""
    rng = random.Random(1)
    dims_k1 = ["only"] * 500
    assert cramers_v(_mcar(rng, 500, 0.3), dims_k1) is None
    dims = ["a"] * 250 + ["b"] * 250
    assert cramers_v([False] * 500, dims) is None
    assert cramers_v([True] * 500, dims) is None
