"""Tier-1 — the meaning-coverage grader over synthetic rows (DAT-853, for DAT-823 W3-F).

Pins :func:`grade_meaning_coverage` in milliseconds without a pipeline: ``'determined'`` /
``'ambiguous'`` / NULL statuses all COUNT as covered when a meaning is present (``'ambiguous'``
is declared ignorance WITH a meaning, not a gap), while a MISSING ColumnConcept row or an
empty/whitespace meaning is the failure the parity oracle catches.
"""

from __future__ import annotations

from types import SimpleNamespace

from calibration.test_meanings_coverage_e2e import grade_meaning_coverage


def _row(
    column: str,
    *,
    has_concept: bool = True,
    meaning: str | None = "a clear meaning",
    meaning_status: str | None = None,
) -> SimpleNamespace:
    """A stand-in for a :class:`MeaningRow`; each test overrides only what it cares about."""
    return SimpleNamespace(
        column=column,
        has_concept=has_concept,
        meaning=meaning,
        meaning_status=meaning_status,
    )


def test_determined_ambiguous_and_null_all_count_as_covered() -> None:
    """A meaning present under any status is covered — the clean-baseline full-coverage case."""
    rows = [
        _row("t.a", meaning_status="determined"),
        _row("t.b", meaning_status="ambiguous"),  # declared ignorance WITH a meaning
        _row("t.c", meaning_status=None),  # a pre-split (old-run) row
    ]
    cov = grade_meaning_coverage(rows)
    assert cov.is_full
    assert cov.covered == ["t.a", "t.b", "t.c"]
    assert cov.by_status == {"determined": 1, "ambiguous": 1, "null": 1}
    assert cov.uncovered == {}


def test_ambiguous_with_a_meaning_is_never_a_failure() -> None:
    """The load-bearing semantic: ``'ambiguous'`` must NOT be graded as uncovered."""
    cov = grade_meaning_coverage(
        [_row("t.x", meaning="unclear but present", meaning_status="ambiguous")]
    )
    assert cov.is_full
    assert cov.covered == ["t.x"]


def test_missing_row_and_empty_meaning_are_uncovered() -> None:
    """A missing concept row and a NULL/blank meaning are both coverage failures, distinctly."""
    rows = [
        _row("t.a", meaning_status="determined"),
        _row("t.missing", has_concept=False, meaning=None),  # no ColumnConcept row
        _row("t.blank", meaning="   ", meaning_status="determined"),  # whitespace-only
        _row("t.null_meaning", meaning=None, meaning_status="ambiguous"),  # row, no meaning
    ]
    cov = grade_meaning_coverage(rows)
    assert not cov.is_full
    assert cov.covered == ["t.a"]
    assert cov.uncovered == {
        "t.blank": "empty meaning",
        "t.missing": "no ColumnConcept row",
        "t.null_meaning": "empty meaning",
    }
