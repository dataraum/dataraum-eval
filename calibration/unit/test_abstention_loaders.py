"""Tier-1 — the calibration loaders honor the engine's abstention schema (DAT-853/DAT-849).

The engine's new abstention primitive makes ``EntropyObjectRecord.score`` nullable:
a detector either MEASURED its question (``status='measured'``, score carries the
answer) or ABSTAINED (``status='abstained'``, score NULL, ``abstain_reason`` says
why — e.g. ``join_path_determinism``'s ``not_applicable`` structural-norm abstention,
DAT-851). The eval loaders rebuild engine ``EntropyObject``s from persisted rows and
aggregate scores; before this fix they defaulted every row to ``status='measured'``
and read ``score`` as a float, so an abstained row either tripped the engine's
construction invariant or reached a ``None`` max-comparison.

These tests pin the representational contract in milliseconds over SYNTHETIC rows
(no docker, no LLM), exercising the extracted pure loaders directly:

  (a) score-based grading skips abstained rows — no score map, no max-comparison,
      no crash (the ``test_temporal_behavior_e2e`` failure, reproduced on a
      relationship-target abstention);
  (b) the banded loader constructs abstained rows VALIDLY and represents them
      faithfully — coverage evidence, NOT dropped, no score, no band — and the real
      band oracle helper does not crash on them (the ``test_band_grading`` failure);
  (c) a MEASURED row with a NULL score is corrupt data (violates the engine's own
      status/score CHECK) and fails LOUD in BOTH loaders — Nones are never
      blanket-swallowed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from dataraum.entropy.loss import get_loss_config
from dataraum.entropy.models import (
    ABSTAIN_INSUFFICIENT_DATA,
    ABSTAIN_NOT_APPLICABLE,
    STATUS_ABSTAINED,
    STATUS_MEASURED,
    relationship_target_key,
)

from calibration.conftest import (
    _aggregate_detector_scores,
    _record_to_entropy_object,
    _records_to_banded_measurements,
)
from calibration.test_band_grading import _non_ready_intents_by_column
from calibration.test_detector_recall import DETECTION_THRESHOLD

# A loss-table detector known to abstain in the wild (DAT-851: ≤1 join path →
# not_applicable). A stable, load-bearing choice: the reproduced failures both
# named it, and it must be a loss measurement to reach EntropyObject construction.
_ABSTAINING_LOSS_DETECTOR = "join_path_determinism"
# An id that is deliberately NOT in the loss table — the banded loader must filter it.
_NON_LOSS_DETECTOR = "not_a_loss_detector_dat853"

_FROM_COL = "col-from-uuid"
_TO_COL = "col-to-uuid"


def _row(**overrides: Any) -> SimpleNamespace:
    """A stand-in for a persisted ``entropy_objects`` row (attribute access, like a
    SQLAlchemy ``Row``). Defaults describe a benign MEASURED column measurement; each
    test overrides only the fields it cares about."""
    base: dict[str, Any] = {
        "object_id": "obj-0",
        "layer": "structural",
        "dimension": "relations",
        "sub_dimension": "relationship_discovery",
        "target": "column:orders.amount",
        "score": 0.0,
        "status": STATUS_MEASURED,
        "abstain_reason": None,
        "evidence": [],
        "detector_id": "null_ratio",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# (a) score-based grading skips abstained rows — the temporal_behavior failure
# ---------------------------------------------------------------------------


def test_score_aggregation_skips_abstained_rows_without_error() -> None:
    """An abstained row never enters a score map or a max-comparison.

    Reproduces the ``test_temporal_behavior_e2e`` setup crash (``'>' not supported
    between NoneType and NoneType``) on the exact shape the run produced: a
    ``join_path_determinism`` relationship-target abstention (score NULL). Measured
    rows of every scope still aggregate; the abstained one is silently excluded (it
    is coverage evidence, surfaced elsewhere), NOT crashed on.
    """
    rel_target = relationship_target_key(_FROM_COL, _TO_COL)
    col_names = {_FROM_COL: ("orders", "customer_id"), _TO_COL: ("customers", "id")}
    records = [
        _row(detector_id="null_ratio", target="column:orders.amount", score=0.5),
        _row(detector_id="cross_table_consistency", target="table:orders", score=0.3),
        # a MEASURED relationship still indexes under BOTH endpoints
        _row(detector_id="relationship_entropy", target=rel_target, score=0.7),
        # the abstained relationship row that crashed _keep_max before the fix
        _row(
            detector_id=_ABSTAINING_LOSS_DETECTOR,
            target=rel_target,
            score=None,
            status=STATUS_ABSTAINED,
            abstain_reason=ABSTAIN_NOT_APPLICABLE,
        ),
    ]

    scores = _aggregate_detector_scores(records, col_names)

    assert scores.column[("orders", "amount", "null_ratio")] == 0.5
    assert scores.table[("orders", "cross_table_consistency")] == 0.3
    # measured relationship present under both endpoints...
    assert scores.relationship[("orders", "customer_id", "relationship_entropy")] == 0.7
    assert scores.relationship[("customers", "id", "relationship_entropy")] == 0.7
    # ...and the abstained detector contributed no score under any key.
    assert not any(det == _ABSTAINING_LOSS_DETECTOR for _, _, det in scores.relationship)


# ---------------------------------------------------------------------------
# (b) the banded loader constructs + represents abstained rows faithfully
# ---------------------------------------------------------------------------


def test_banded_loader_represents_abstained_rows_faithfully() -> None:
    """An abstained loss row constructs validly and rides the banded surface as
    coverage evidence — never dropped, no score, no band — and the measured rows
    still band. The engine's ``measured_score`` is never called on the abstention
    (it would raise); the band surface honors that.
    """
    cfg = get_loss_config()
    rel_target = relationship_target_key(_FROM_COL, _TO_COL)
    records = [
        # the DAT-849 signature: score 0.0, evidence ignorance 0.811 -> investigate
        _row(
            detector_id="temporal_behavior",
            target="column:fx_rates.rate",
            score=0.0,
            evidence=[{"ignorance": 0.811}],
        ),
        # abstained loss row (score NULL) — must construct + survive as coverage
        _row(
            detector_id=_ABSTAINING_LOSS_DETECTOR,
            target=rel_target,
            score=None,
            status=STATUS_ABSTAINED,
            abstain_reason=ABSTAIN_NOT_APPLICABLE,
        ),
        # non-loss detector — filtered out before construction
        _row(detector_id=_NON_LOSS_DETECTOR, target="column:x.y", score=0.5),
    ]

    measurements = _records_to_banded_measurements(records, cfg)

    by_detector = {m.detector_id: m for m in measurements}
    assert _NON_LOSS_DETECTOR not in by_detector, "non-loss detector should be filtered"

    # The abstained one is PRESENT (coverage evidence), not dropped.
    abstained = by_detector[_ABSTAINING_LOSS_DETECTOR]
    assert abstained.is_abstained()
    assert abstained.status == STATUS_ABSTAINED
    assert abstained.abstain_reason == ABSTAIN_NOT_APPLICABLE
    assert abstained.score is None and abstained.conflict is None
    assert abstained.intent_risk == {} and abstained.intent_band == {}
    assert not abstained.is_non_ready()
    assert abstained.worst_band() == "ready"

    # The measured DAT-849 row still bands non-ready through ignorance.
    measured = by_detector["temporal_behavior"]
    assert measured.is_non_ready()
    assert measured.intent_band["aggregation_intent"] == "investigate"

    # The REAL band oracle helper (not a look-alike) does not crash on the mix, and
    # ONLY the measured column banded: the graded key set is EXACTLY the measured
    # column — the abstained relationship row (and the filtered non-loss row)
    # contribute nothing to the surface.
    graded = _non_ready_intents_by_column(measurements)
    assert set(graded) == {("fx_rates", "rate")}
    assert "aggregation_intent" in graded[("fx_rates", "rate")]


def test_column_target_abstention_survives_the_zero_score_oracle_filter() -> None:
    """The ``test_zero_score_bands_are_corroborated`` filter compares ``score <
    DETECTION_THRESHOLD``; a column-target abstention (score None) must never reach
    that comparison. ``is_non_ready()`` is False for an abstention, so the ``and``
    short-circuits — this pins that the None score raises no TypeError there.
    """
    cfg = get_loss_config()
    records = [
        _row(
            detector_id="null_semantics",
            target="column:accounts.notes",
            score=None,
            status=STATUS_ABSTAINED,
            abstain_reason=ABSTAIN_INSUFFICIENT_DATA,
        ),
    ]

    measurements = _records_to_banded_measurements(records, cfg)

    # The exact predicate from the Tier-3 oracle — must not raise on the None score.
    zero_score_non_ready = [
        m
        for m in measurements
        if (
            m.target.startswith("column:")
            and m.is_non_ready()
            and m.score is not None  # non-ready ⇒ measured (never an abstention)
            and m.score < DETECTION_THRESHOLD
        )
    ]
    assert zero_score_non_ready == []


# ---------------------------------------------------------------------------
# (c) a corrupt MEASURED NULL score fails LOUD in both loaders
# ---------------------------------------------------------------------------


def test_corrupt_measured_null_score_fails_loud_in_score_aggregation() -> None:
    """A row claiming ``status='measured'`` with score NULL is corrupt (the engine's
    status/score pairing forbids it). The score loader must RAISE, not silently drop
    it — a blanket ``if score is None: continue`` would hide a real data bug.
    """
    records = [_row(detector_id="null_ratio", target="column:orders.amount", score=None)]
    with pytest.raises(ValueError, match="NULL score"):
        _aggregate_detector_scores(records, {})


def test_corrupt_measured_null_score_fails_loud_in_object_reconstruction() -> None:
    """Same corruption through the record->object path: the engine's own
    ``__post_init__`` invariant raises (a measured object requires a score). The
    banded loader does not swallow it.
    """
    corrupt = _row(detector_id="temporal_behavior", target="column:fx_rates.rate", score=None)

    with pytest.raises(ValueError, match="requires a score"):
        _record_to_entropy_object(corrupt)

    cfg = get_loss_config()
    with pytest.raises(ValueError, match="requires a score"):
        _records_to_banded_measurements([corrupt], cfg)
