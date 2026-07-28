"""Tier-1: the pipeline-error measurement's rules (DAT-687) — no lake, no corpus.

What has to be right here is not arithmetic, it is *what may be compared to what*.
The measurement's whole value rests on refusing to compare an engine metric with a
same-named eval metric that measures a different population — the 77%-error trap
that `gross_profit` walked into on the very first read.
"""

from __future__ import annotations

import pytest

from calibration import pipeline_error as pe


def _q(name: str, value: float | None, *, kind: str = "extract",
       grounding_class: str = pe.TYPED, error: str = "") -> pe.Quantity:
    return pe.Quantity(
        name=name, kind=kind, value=value, grounding_class=grounding_class, error=error
    )


TRUTH = {
    "total_revenue": 51_766_199.72,
    "ending_ar_balance": 13_070_114.83,
    "annual_dso": 92.2,
}


def _quantities(**overrides: float | None) -> list[pe.Quantity]:
    base: dict[str, float | None] = {
        "revenue": 51_766_199.72,
        "accounts_receivable": 13_070_114.83,
        "dso": 92.1565,
    }
    base.update(overrides)
    return [
        _q("revenue", base["revenue"]),
        _q("accounts_receivable", base["accounts_receivable"], grounding_class=pe.NAMED),
        _q("dso", base["dso"], kind="metric", grounding_class=pe.DERIVED),
    ]


# ---------------------------------------------------------------------------
# grounding class — the attribution axis
# ---------------------------------------------------------------------------


def test_classify_reads_how_the_population_was_selected() -> None:
    assert pe._classify(["account_id__account_type IN ('revenue')"]) == pe.TYPED
    assert pe._classify(["account_id__name IN ('Trade Payables')"]) == pe.NAMED
    assert pe._classify(
        ["account_id__account_type IN ('expense')", "account_id__name IN ('Rent')"]
    ) == pe.MIXED
    assert pe._classify(["period = (SELECT MAX(period) FROM x)"]) == pe.UNKNOWN
    assert pe._classify([]) == pe.UNKNOWN


# ---------------------------------------------------------------------------
# pairing — like-for-like or not at all
# ---------------------------------------------------------------------------


def test_graded_pairs_reproduce_truth() -> None:
    report = pe.measure("clean", quantities=_quantities(), truth=TRUTH)
    assert {r.engine for r in report.graded} == {"revenue", "accounts_receivable", "dso"}
    assert all(r.in_tolerance for r in report.graded)
    by_engine = {r.engine: r for r in report.graded}
    assert by_engine["dso"].absolute_error == pytest.approx(0.0435, abs=1e-4)
    assert by_engine["revenue"].relative_error_pct == pytest.approx(0.0, abs=1e-9)


def test_every_pair_declares_exactly_one_tolerance_and_a_reason() -> None:
    """A pair with no stated `why` is an unexamined comparison waiting to mislead."""
    for pair in pe.PAIRS:
        has_pct = pair.tolerance_pct is not None
        has_abs = pair.tolerance_abs is not None
        assert has_pct != has_abs, f"{pair.engine}: set exactly one tolerance form"
        assert len(pair.why) > 40, f"{pair.engine}: state why the populations match"


def test_a_definitionally_different_metric_is_never_graded() -> None:
    """`gross_profit` means revenue−COGS to the engine and revenue−ALL-expenses to us.

    Grading it produced a 77% "error" that was entirely our own definition. It must
    stay out of the graded set and carry the reason instead — filing that against the
    engine is the rumour the charter forbids.
    """
    assert "gross_profit" not in {p.engine for p in pe.PAIRS}
    reason = pe.UNPAIRED["gross_profit"]
    assert "definition differs" in reason

    report = pe.measure(
        "clean",
        quantities=[*_quantities(), _q("gross_profit", 49_983_469.08, kind="metric")],
        truth={**TRUTH, "gross_profit": 28_239_122.13},
    )
    assert "gross_profit" not in {r.engine for r in report.graded}
    assert report.unpaired["gross_profit"] == reason


def test_unpaired_quantity_without_a_reason_is_flagged_not_hidden() -> None:
    report = pe.measure(
        "clean", quantities=[*_quantities(), _q("brand_new_metric", 1.0)], truth=TRUTH
    )
    assert report.unpaired["brand_new_metric"].startswith("not paired and no reason recorded")


def test_a_valueless_quantity_is_unavailable_not_zero() -> None:
    """A metric whose SQL failed must never be graded as 0 — that is a silent pass."""
    report = pe.measure(
        "clean",
        quantities=_quantities(revenue=None),
        truth=TRUTH,
    )
    assert "revenue" not in {r.engine for r in report.graded}
    assert "revenue" in report.unavailable


def test_missing_truth_key_is_unavailable() -> None:
    report = pe.measure("clean", quantities=_quantities(), truth={"total_revenue": 1.0})
    assert {r.engine for r in report.graded} == {"revenue"}
    assert set(report.unavailable) == {"accounts_receivable", "dso"}


# ---------------------------------------------------------------------------
# tolerance + distribution
# ---------------------------------------------------------------------------


def test_tolerance_form_decides_which_error_is_judged() -> None:
    pct = pe.ErrorRow(
        engine="x", truth_key="x", unit="currency", grounding_class=pe.TYPED,
        computed=101.0, expected=100.0, relative_error_pct=1.0, absolute_error=1.0,
        tolerance_pct=1.0, tolerance_abs=None,
    )
    assert pct.in_tolerance and pct.threshold == 1.0 and pct.error == 1.0

    # A days metric judged on an absolute bar: 2 days off 92 is 2.2% — out on a pct
    # bar, comfortably in on the 3-day KPI bar. The declared form decides.
    days = pe.ErrorRow(
        engine="dso", truth_key="annual_dso", unit="days", grounding_class=pe.DERIVED,
        computed=94.2, expected=92.2, relative_error_pct=2.17, absolute_error=2.0,
        tolerance_pct=None, tolerance_abs=3.0,
    )
    assert days.in_tolerance and days.threshold == 3.0 and days.error == 2.0


def test_out_of_tolerance_is_reported_not_smoothed() -> None:
    report = pe.measure("clean", quantities=_quantities(revenue=60_000_000.0), truth=TRUTH)
    dist = report.distribution
    assert dist["out_of_tolerance"] == ["revenue"]
    assert dist["max_pct"] > 15.0


def test_distribution_attributes_error_by_grounding_class() -> None:
    """RFC 1's open question: attribute a band to the KIND of recovery, not to a lump."""
    dist = pe.measure("clean", quantities=_quantities(), truth=TRUTH).distribution
    assert dist["n"] == 3
    assert set(dist["by_grounding_class"]) == {pe.TYPED, pe.NAMED, pe.DERIVED}
    assert dist["by_grounding_class"][pe.DERIVED]["n"] == 1


def test_empty_distribution_says_nothing_rather_than_zero() -> None:
    dist = pe.measure("clean", quantities=[], truth=TRUTH).distribution
    assert dist["n"] == 0 and dist["max_pct"] is None and dist["median_pct"] is None


# ---------------------------------------------------------------------------
# the engine's own declared conditions
# ---------------------------------------------------------------------------


def test_condition_holds_evaluates_the_declared_grammar() -> None:
    assert pe._condition_holds("0 <= value <= 365", 92.15) is True
    assert pe._condition_holds("0 <= value <= 365", -124.73) is False
    assert pe._condition_holds("0 <= value <= 365", 400.0) is False
    assert pe._condition_holds("value >= 0", 13.8) is True
    assert pe._condition_holds("value >= -1", -0.5) is True


def test_condition_holds_refuses_what_it_cannot_parse() -> None:
    """Unparseable is None — never a guess, and never `eval` on config text."""
    assert pe._condition_holds("value is reasonable", 1.0) is None
    assert pe._condition_holds("__import__('os').system('x')", 1.0) is None
    assert pe._condition_holds("other_metric <= value", 1.0) is None
    assert pe._condition_holds("0 <= value <=", 1.0) is None
