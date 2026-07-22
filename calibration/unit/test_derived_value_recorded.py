"""Derived-value grounding net (Phase 4) — the cheap backbone net for `derived_value`.

`derived_value` scores a column that stops matching its derivation formula. The grounded
statistic is the **formula-violation rate**: the fraction of rows where the target column
disagrees with the identity that holds on clean data. Recall is ordering (charter):
injected > clean + margin, never a point threshold.

The reference identity is discovered from the fixture, not assumed: on clean
`journal_lines`, `net_amount == debit − credit` holds on 100% of rows (25172/25172) — so
it IS the column's derivation. DRIFT-0010 breaks it on ~13% of the injected rows. The net
uses that identity as the ground-truth instrument; it does not reimplement the engine's
formula discovery.

- Tier 1: the statistic is 0 on a formula-conforming column and rises with corruption.
- Tier 2: over the recorded fixture, clean violates 0%, the injected column violates more.
"""

from __future__ import annotations

from calibration.unit.fixture import load_fixture, row_records

EPS = 0.005  # half a cent — float slack, well below any injected drift


def _num(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def formula_violation_rate(
    records: list[dict[str, str]], target_col: str, terms: list[tuple[str, int]]
) -> float:
    """Fraction of rows where ``target_col`` != Σ(sign·col) over ``terms``.

    ``terms`` encodes the identity, e.g. ``[("debit", 1), ("credit", -1)]`` for
    ``net_amount == debit − credit``. Rows with any missing operand are skipped (can't
    evaluate the identity). Returns 0.0 for no evaluable rows.
    """
    total = violations = 0
    for r in records:
        target = _num(r.get(target_col))
        operands = {c: _num(r.get(c)) for c, _ in terms}
        if target is None or any(v is None for v in operands.values()):
            continue
        nums = {c: v for c, v in operands.items() if v is not None}  # narrowed past the guard
        expected = sum(sign * nums[c] for c, sign in terms)
        total += 1
        if abs(target - expected) > EPS:
            violations += 1
    return violations / total if total else 0.0


def test_formula_violation_rate_separates_synthetic() -> None:
    terms = [("a", 1), ("b", -1)]  # x == a − b
    conforming = [{"x": str(i), "a": str(i), "b": "0"} for i in range(100)]
    corrupted = [
        {"x": str(i + (5 if i % 4 == 0 else 0)), "a": str(i), "b": "0"} for i in range(100)
    ]
    assert formula_violation_rate(conforming, "x", terms) == 0.0
    assert formula_violation_rate(corrupted, "x", terms) == 0.25  # every 4th row broken


def test_derived_value_injection_separates_from_clean_recorded() -> None:
    conn = load_fixture()
    terms = [("debit", 1), ("credit", -1)]  # net_amount == debit − credit
    try:
        clean = formula_violation_rate(row_records(conn, "clean", "journal_lines"), "net_amount", terms)
        injected = formula_violation_rate(
            row_records(conn, "detection-v1", "journal_lines"), "net_amount", terms
        )
    finally:
        conn.close()
    # The identity holds on ALL clean rows — that is what grounds it as the formula.
    assert clean == 0.0, f"reference identity does not hold on clean: violation rate {clean:.4f}"
    assert injected > clean + 0.05, f"drift did not separate: injected={injected:.4f} clean={clean:.4f}"
