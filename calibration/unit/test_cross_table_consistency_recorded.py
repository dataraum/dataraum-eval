"""Cross-table grounding net (Phase 4) — the cheap backbone net for `cross_table_consistency`.

`cross_table_consistency` fires when two tables that should reconcile stop agreeing.
The grounded statistic is the **reconciliation-mismatch rate**: the fraction of joined
rows where a known cross-table identity is violated. Recall is ordering (charter):
injected > clean + margin, never a point threshold.

The graded relationship is `payments ⋈ bank_transactions` on `payment_id`, identity
`payment.amount == −bank.amount` (a bank outflow is the negative of the payment). This
identity is DISCOVERED from clean, not assumed: it holds on 2585/2585 clean pairs — so
it IS the reconciliation. On detection-v1 it is violated on ~77% of pairs.

Honest scope: that 77% is an AGGREGATE. detection-v1 perturbs the payment/bank amounts
three ways — break_payment_bank_match (0.15) scales payments, and benford round_numbers
+ temporal_drift (1.35×) scale bank_transactions.amount. Every one of them is a genuine
cross-table inconsistency this reconciliation should catch, so the net grades the
reconciliation itself, not any single injector (an isolated cross-table cal strategy
would give a per-injector margin — a later refinement). What grounds it is the clean
side: the identity holds on 100% of clean pairs.

- Tier 1: the statistic is 0 when both sides agree and rises when one side is scaled.
- Tier 2: over the recorded fixture, clean reconciles 0%, the injected twin does not.

If the recorded leg had NOT separated, that is a finding (like the outlier_rate CUT),
filed, never a relaxed assertion. It separates by a wide margin.
"""

from __future__ import annotations

from calibration.unit.fixture import load_fixture, row_records


def _num(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def reconciliation_mismatch_rate(
    left: list[dict[str, str]],
    right: list[dict[str, str]],
    join_key: str,
    left_amount: str,
    right_amount: str,
    *,
    right_sign: int = 1,
    eps: float = 0.005,
) -> float:
    """Fraction of ``left`` rows whose amount != ``right_sign`` · matched right amount.

    Rows are joined on ``join_key``; a left row with no join match or a missing amount
    is skipped (nothing to reconcile). ``right_sign`` encodes the convention (−1 when a
    bank outflow is the negative of the payment). Returns 0.0 when no pair is evaluable.
    """
    right_amt = {
        r.get(join_key): _num(r.get(right_amount))
        for r in right
        if r.get(join_key) not in (None, "")
    }
    total = violations = 0
    for row in left:
        la = _num(row.get(left_amount))
        ra = right_amt.get(row.get(join_key))
        if la is None or ra is None:
            continue
        total += 1
        if abs(la - right_sign * ra) > eps:
            violations += 1
    return violations / total if total else 0.0


def test_reconciliation_mismatch_separates_synthetic() -> None:
    left = [{"k": str(i), "amt": str(i * 1.0)} for i in range(100)]
    # right mirrors left with the opposite sign; corrupt every 4th so it no longer reconciles.
    right = [{"k": str(i), "amt": str(-i * 1.0 * (2 if i % 4 == 0 else 1))} for i in range(100)]
    clean_right = [{"k": str(i), "amt": str(-i * 1.0)} for i in range(100)]
    assert reconciliation_mismatch_rate(left, clean_right, "k", "amt", "amt", right_sign=-1) == 0.0
    # every 4th corrupted, but i=0 has amount 0 (0 == -0) so 24 of 100 actually differ
    assert reconciliation_mismatch_rate(left, right, "k", "amt", "amt", right_sign=-1) == 0.24


def test_cross_table_injection_separates_from_clean_recorded() -> None:
    conn = load_fixture()
    try:
        clean = reconciliation_mismatch_rate(
            row_records(conn, "clean", "payments"),
            row_records(conn, "clean", "bank_transactions"),
            "payment_id",
            "amount",
            "amount",
            right_sign=-1,
        )
        injected = reconciliation_mismatch_rate(
            row_records(conn, "detection-v1", "payments"),
            row_records(conn, "detection-v1", "bank_transactions"),
            "payment_id",
            "amount",
            "amount",
            right_sign=-1,
        )
    finally:
        conn.close()
    # The identity holds on ALL clean pairs — that is what grounds the reconciliation.
    assert clean == 0.0, f"reconciliation does not hold on clean: mismatch rate {clean:.4f}"
    assert injected > clean + 0.10, f"cross-table break did not separate: injected={injected:.4f} clean={clean:.4f}"
