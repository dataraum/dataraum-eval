"""Type-fidelity grounding net (Phase 4) — the cheap backbone net for `type_fidelity`.

`type_fidelity` fires when a column stops holding values of its inferred type. The
grounded statistic is the **type-nonconformance rate**: the fraction of non-null
values that fail to parse as the column's expected type (numeric here). Recall is
ordering (charter): injected > clean + margin, never a point threshold.

The graded column is `journal_lines.debit` — numeric on clean data (every cell
parses as float, nonconformance 0). `corrupt_types` (ratio 0.15) drops VARCHAR
garbage into ~15% of the cells, driving the nonconformance rate up. This net is why
the capture keeps a majority-numeric column even with corruption mixed in
(`_NUMERIC_FRACTION`) — a numeric measure that stops being fully numeric is exactly
what type_fidelity grades, so the fixture must retain it.

- Tier 1: the statistic is 0 on a fully-numeric column and rises with injected garbage.
- Tier 2: over the recorded fixture, clean debit is 0% nonconforming, the corrupted
  twin (detection-typing-v1) is materially higher.

If the recorded leg had NOT separated, that is a finding (like the outlier_rate CUT),
filed, never a relaxed assertion. It separates by the full injection ratio.
"""

from __future__ import annotations

from collections.abc import Sequence

from calibration.unit.fixture import column_cells, load_fixture


def numeric_nonconformance_rate(cells: Sequence[object]) -> float:
    """Fraction of non-null ``cells`` that do NOT parse as float.

    ``None`` cells (blanks) are skipped — a missing value is a null, not a type
    violation (that is null_ratio's concern). Returns 0.0 when every cell is null.
    """
    present = [c for c in cells if c is not None]
    if not present:
        return 0.0
    bad = 0
    for c in present:
        try:
            float(c)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            bad += 1
    return bad / len(present)


def test_numeric_nonconformance_separates_synthetic() -> None:
    clean = [str(i * 1.5) for i in range(100)]  # all parse as float
    corrupted = ["N/A" if i % 4 == 0 else str(i * 1.5) for i in range(100)]  # every 4th garbage
    assert numeric_nonconformance_rate(clean) == 0.0
    assert numeric_nonconformance_rate(corrupted) == 0.25


def test_type_corruption_separates_from_clean_recorded() -> None:
    # corrupt_types drops VARCHAR garbage into 15% of journal_lines.debit; the numeric
    # nonconformance rate must exceed the clean twin's (ordering, not a threshold).
    conn = load_fixture()
    try:
        clean = numeric_nonconformance_rate(column_cells(conn, "clean", "journal_lines", "debit"))
        injected = numeric_nonconformance_rate(
            column_cells(conn, "detection-typing-v1", "journal_lines", "debit")
        )
    finally:
        conn.close()
    # Clean debit is fully numeric — that is what grounds "numeric" as its true type.
    assert clean == 0.0, f"clean debit is not fully numeric: nonconformance {clean:.4f}"
    assert injected > clean + 0.05, f"type corruption did not separate: injected={injected:.4f} clean={clean:.4f}"
