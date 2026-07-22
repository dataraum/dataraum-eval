"""Benford grounding net (Phase 4) — the cheap backbone net for `benford`.

The frontier scoreboard showed `benford` firing on the pipeline, but a regression in it
is caught today only by a Tier-3 run. This is the ms-speed net: does the NAMED statistic
— first-digit Mean Absolute Deviation from Benford's law (Nigrini's MAD) — separate the
injected family from clean, as ordering (charter: injected > clean + margin, never a
point threshold)?

- Tier 1: the pure statistic separates a Benford-conforming synthetic column from a
  first-digit-tampered one — proves the instrument itself works.
- Tier 2: over the recorded fixture, the real injected column (`bank_transactions.amount`,
  BENFORD-0003) deviates more than its clean twin.

If the recorded leg had NOT separated, that is a finding (like the outlier_rate CUT —
"this statistic can't separate the injection from clean financial structure"), filed,
never a relaxed assertion. It does separate, by a wide margin (see the recorded test).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from calibration.unit.fixture import column_values, load_fixture

# Benford's law: P(first significant digit = d) = log10(1 + 1/d), d = 1..9.
BENFORD_P = [math.log10(1 + 1 / d) for d in range(1, 10)]


def first_digit(value: float) -> int | None:
    """The first significant digit of |value| (1..9), or None for zero."""
    v = abs(value)
    if v == 0:
        return None
    while v >= 10:
        v /= 10
    while v < 1:
        v *= 10
    return int(v)


def benford_mad(values: Sequence[float]) -> float:
    """Mean absolute deviation of the observed first-digit frequencies from Benford.

    Nigrini's MAD: mean over digits 1..9 of |observed_freq(d) − benford_p(d)|. 0.0 is a
    perfect Benford fit; a first-digit-tampered column drives it up. Returns 0.0 for an
    empty column (no digits to disagree).
    """
    digits = [d for v in values if (d := first_digit(v)) is not None]
    if not digits:
        return 0.0
    n = len(digits)
    observed = [digits.count(d) / n for d in range(1, 10)]
    return sum(abs(o - p) for o, p in zip(observed, BENFORD_P, strict=True)) / 9


def test_benford_mad_separates_synthetic() -> None:
    # A Benford-conforming column (first digits distributed ~log) vs one tampered to
    # cluster on a single leading digit — MAD must be far higher on the tampered one.
    conforming = [d * 10**k for d in range(1, 10) for k in range(4) for _ in range(int(1000 * BENFORD_P[d - 1]))]
    tampered = list(range(5000, 6000))  # every value leads with '5'
    assert benford_mad(conforming) < 0.02
    assert benford_mad(tampered) > 0.15
    assert benford_mad(tampered) > benford_mad(conforming) + 0.1


def test_benford_injection_separates_from_clean_recorded() -> None:
    # BENFORD-0003 tampers bank_transactions.amount; its first-digit MAD must exceed the
    # clean twin's by a real margin (ordering, not a tuned threshold).
    conn = load_fixture()
    try:
        injected = benford_mad(column_values(conn, "detection-v1", "bank_transactions", "amount"))
        clean = benford_mad(column_values(conn, "clean", "bank_transactions", "amount"))
    finally:
        conn.close()
    assert injected > clean, f"benford MAD did not separate: injected={injected:.4f} clean={clean:.4f}"
    # A margin that reflects a real gap, not a hair over clean's financial noise floor.
    assert injected > clean + 0.03, f"separation too thin: injected={injected:.4f} clean={clean:.4f}"
