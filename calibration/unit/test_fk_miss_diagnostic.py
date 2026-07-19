"""Tier-1: the FK recall-miss diagnostic picks the right explanation (DAT-725).

Run #2's forensics: a truth pair confirmed in the FLIPPED orientation
(payments.payment_id -> bank_transactions.payment_id at 0.95) was printed as
"judge DECLINED at confidence 1.0" — the diagnostic read only the
direction-insensitive candidate row and never looked at confirmed rows. The
grading itself is direction-exact (the red stands); only the printed WHY was a
mis-diagnosis. ``pick_fk_miss_diagnostic`` is the pure half of the reader, so
the preference order is pinned here without PG.
"""

from __future__ import annotations

from typing import Any

from calibration.metadata_truth import pick_fk_miss_diagnostic

# Truth pair (direction-exact): bank_transactions.payment_id -> payments.payment_id.
_PAIR = ("bank_transactions", "payment_id", "payments", "payment_id")


def _row(
    ft: str, fc: str, tt: str, tc: str, method: str, confidence: float, evidence: Any = None
) -> tuple[str, str, str, str, str, float, Any]:
    return (ft, fc, tt, tc, method, confidence, evidence)


def test_flipped_confirm_wins_over_candidate() -> None:
    """The run-#2 shape: a flipped CONFIRMED row explains the miss, not the
    coexisting direction-insensitive candidate row."""
    rows = [
        _row("payments", "payment_id", "bank_transactions", "payment_id", "candidate", 1.0),
        _row("payments", "payment_id", "bank_transactions", "payment_id", "foreign_key", 0.95),
    ]
    diag = pick_fk_miss_diagnostic(rows, _PAIR)
    assert diag is not None
    assert diag["kind"] == "confirmed_flipped"
    assert diag["confidence"] == 0.95


def test_candidate_either_orientation_is_a_decline() -> None:
    """No confirmed row → the kept candidate row IS the judge's decline, matched
    direction-insensitively (the judge's orientation is not run-stable)."""
    for ft, fc, tt, tc in (_PAIR, (_PAIR[2], _PAIR[3], _PAIR[0], _PAIR[1])):
        diag = pick_fk_miss_diagnostic(
            [_row(ft, fc, tt, tc, "candidate", 0.4, evidence={"reason": "weak overlap"})],
            _PAIR,
        )
        assert diag is not None
        assert diag["kind"] == "declined"
        assert diag["confidence"] == 0.4
        assert diag["evidence"] == {"reason": "weak overlap"}


def test_declined_tiebreak_is_reproducible() -> None:
    """Several matching candidate rows: the exact-orientation row's evidence wins
    over the flipped one, then the higher confidence — independent of SQL row
    order, so the printed diagnostic is reproducible across runs."""
    exact = _row(*_PAIR, "candidate", 0.3, evidence={"which": "exact"})
    flipped = _row(
        _PAIR[2], _PAIR[3], _PAIR[0], _PAIR[1], "candidate", 0.9, evidence={"which": "flipped"}
    )
    for rows in ([exact, flipped], [flipped, exact]):
        diag = pick_fk_miss_diagnostic(rows, _PAIR)
        assert diag is not None
        assert diag["evidence"] == {"which": "exact"}

    hi = _row(*_PAIR, "candidate", 0.8, evidence={"which": "hi"})
    lo = _row(*_PAIR, "candidate", 0.2, evidence={"which": "lo"})
    for rows in ([hi, lo], [lo, hi]):
        diag = pick_fk_miss_diagnostic(rows, _PAIR)
        assert diag is not None
        assert diag["evidence"] == {"which": "hi"}


def test_no_matching_row_is_a_layer_a_gap() -> None:
    """Nothing about the pair in the run's rows → None (never a candidate)."""
    rows = [
        _row("invoices", "entry_id", "journal_entries", "entry_id", "foreign_key", 0.9),
        _row("trial_balance", "period", "balance_sheet", "period", "candidate", 0.6),
    ]
    assert pick_fk_miss_diagnostic(rows, _PAIR) is None


def test_flipped_confirm_is_surrogate_aware() -> None:
    """A DAT-277 surrogate composite embedding the truth column matches, exactly
    like the recall test's ``_satisfies`` containment."""
    rows = [
        _row("payments", "_sk__date__payment_id", "bank_transactions", "payment_id", "llm", 0.8)
    ]
    diag = pick_fk_miss_diagnostic(rows, _PAIR)
    assert diag is not None
    assert diag["kind"] == "confirmed_flipped"


def test_same_orientation_confirm_is_not_reported_as_flipped() -> None:
    """A confirmed row in the TRUTH orientation never explains a miss as flipped
    (it would have satisfied recall; defensively it must not match here)."""
    rows = [_row(*_PAIR, "foreign_key", 0.9)]
    assert pick_fk_miss_diagnostic(rows, _PAIR) is None
