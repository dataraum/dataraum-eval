"""Fire-rate scoreboard (Phase 3) — pure aggregation over synthetic entropy rows, Tier 1.

Exercises the frontier grade with no pipeline: coverage, fire rate, the score
distribution, and the three findings flags (mute / never-fired / saturated) that turn
"a detector found nothing" from an invisible green into a visible finding.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from calibration.scoreboard import (
    SATURATION_MIN_N,
    build_scoreboard,
    render,
)

SLICE = frozenset({"benford", "relationship_entropy", "null_ratio", "type_fidelity"})


def _row(detector: str, target: str, score: float | None, status: str = "measured") -> SimpleNamespace:
    return SimpleNamespace(detector_id=detector, target=target, status=status, score=score)


def test_fire_rate_and_distribution() -> None:
    rows = [
        _row("benford", "column:t.a", 0.8),
        _row("benford", "column:t.b", 0.0),  # measured, did not fire
        _row("benford", "column:t.c", 0.4),
    ]
    board = build_scoreboard(rows, SLICE, strategy="s")
    (b,) = board.per_detector
    assert (b.n_measured, b.n_fired, b.n_abstained) == (3, 2, 0)
    assert b.fire_rate == pytest.approx(2 / 3)
    assert b.score_max == 0.8 and b.score_min == 0.0 and b.score_median == pytest.approx(0.4)
    assert b.in_slice is True and b.status == "active"


def test_demoted_detector_silence_is_never_a_finding() -> None:
    # dimensional_entropy is in-slice but DEMOTED (real case: NMI anti-predictive off the
    # loss path). Its silence — zero rows, or measured-but-0.0, or firing everywhere — must
    # never raise mute/never-fired/saturated, else the scoreboard cries wolf and is ignored.
    slice_with_demoted = SLICE | {"dimensional_entropy"}
    demoted = frozenset({"dimensional_entropy"})

    # (a) zero rows → not mute
    b1 = build_scoreboard(
        [_row("benford", "column:t.a", 0.5)], slice_with_demoted, demoted=demoted
    )
    assert "dimensional_entropy" not in b1.mute
    assert "benford" not in b1.mute  # benford emitted

    # (b) ran, all 0.0 → not never-fired; status is surfaced as demoted
    rows = [_row("dimensional_entropy", f"column:t.c{i}", 0.0) for i in range(3)]
    b2 = build_scoreboard(rows, slice_with_demoted, demoted=demoted)
    assert b2.never_fired == [] and b2.mute == sorted(SLICE)  # the 4 active ones are mute
    assert next(s for s in b2.per_detector if s.detector_id == "dimensional_entropy").status == "demoted"

    # (c) fires on everything → not saturated
    hot = [_row("dimensional_entropy", f"column:t.h{i}", 0.9) for i in range(SATURATION_MIN_N)]
    assert build_scoreboard(hot, slice_with_demoted, demoted=demoted).saturated == []


def test_abstentions_are_coverage_not_scores() -> None:
    rows = [
        _row("relationship_entropy", "rel:1::2", None, status="abstained"),
        _row("relationship_entropy", "rel:3::4", 0.5),
    ]
    board = build_scoreboard(rows, SLICE, strategy="s")
    (b,) = board.per_detector
    assert b.n_abstained == 1 and b.n_measured == 1 and b.n_fired == 1
    assert b.n_targets == 2  # both rows count toward coverage


def test_measured_null_score_is_corrupt_and_raises() -> None:
    rows = [_row("benford", "column:t.a", None, status="measured")]
    with pytest.raises(ValueError, match="NULL score"):
        build_scoreboard(rows, SLICE, strategy="s")


def test_mute_flags_in_slice_detector_with_zero_rows() -> None:
    # benford emitted; the other three slice detectors are silent → all three MUTE.
    rows = [_row("benford", "column:t.a", 0.3)]
    board = build_scoreboard(rows, SLICE, strategy="s")
    assert set(board.mute) == {"relationship_entropy", "null_ratio", "type_fidelity"}
    assert board.never_fired == [] and board.saturated == []


def test_never_fired_flags_a_detector_that_ran_but_scored_zero() -> None:
    rows = [_row("null_ratio", f"column:t.c{i}", 0.0) for i in range(3)]
    board = build_scoreboard(rows, SLICE, strategy="s")
    assert board.never_fired == ["null_ratio"]
    assert "null_ratio" not in board.mute  # it ran — not mute


def test_saturated_needs_both_high_rate_and_enough_n() -> None:
    hot = [_row("benford", f"column:t.h{i}", 0.7) for i in range(SATURATION_MIN_N)]
    board = build_scoreboard(hot, SLICE, strategy="s")
    assert board.saturated == ["benford"]

    # Same 100% fire rate but under the min-n floor → not flagged (too few to matter).
    thin = [_row("benford", "column:t.x", 0.7), _row("benford", "column:t.y", 0.7)]
    assert build_scoreboard(thin, SLICE, strategy="s").saturated == []


def test_off_slice_active_is_informational_not_a_finding() -> None:
    rows = [_row("join_path_determinism", "rel:1::2", 0.9)]
    board = build_scoreboard(rows, SLICE, strategy="s")
    assert board.off_slice_active == ["join_path_determinism"]
    assert board.mute == sorted(SLICE)  # every slice detector is silent
    # an off-slice detector is never counted as never_fired/saturated-as-a-finding
    assert board.never_fired == []


def test_sorted_loudest_first() -> None:
    rows = [
        _row("null_ratio", "column:t.a", 0.0),  # fire_rate 0
        _row("benford", "column:t.b", 0.9),  # fire_rate 1.0
    ]
    board = build_scoreboard(rows, SLICE, strategy="s")
    assert [s.detector_id for s in board.per_detector] == ["benford", "null_ratio"]


def test_to_dict_and_render_are_stable() -> None:
    rows = [_row("benford", "column:t.a", 0.5)]
    board = build_scoreboard(rows, SLICE, strategy="rel-f1")
    d = board.to_dict()
    assert d["strategy"] == "rel-f1" and d["fire_threshold"] == 0.0
    assert d["per_detector"][0]["detector_id"] == "benford"

    text = render(board, is_wild=True)
    assert "fire-rate scoreboard: rel-f1" in text and "wild (no recall truth)" in text
    # synthetic framing differs — recall is assertable, say so
    assert "recall IS assertable" in render(board, is_wild=False)
