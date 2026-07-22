"""Tier-1 — the readiness BAND surface is graded, not just the score (DAT-849).

The product bands each intent on expected loss over ``(conflict, ignorance)``, so a
measurement can score ``0.0`` and still drive a non-ready band through ignorance
alone. The score oracles (``test_detector_recall``, ``DETECTION_THRESHOLD`` on
``score``) are blind to that. These tests prove, in milliseconds over synthetic
``EntropyObject`` rows and the engine's OWN loss rollup (no docker, no LLM):

  * the DAT-849 signature (``score=0.0``, evidence ignorance ``0.811``,
    ``temporal_behavior``) bands ``investigate`` and is caught by the band surface;
  * a score-only reading at ``DETECTION_THRESHOLD`` would pass that same row
    silently — a documented CONTRAST, not a weakening of the score oracle;
  * every detector in the engine loss table has its banded outcome reachable
    through the graded surface — an evidence-driven non-ready band is graded by
    band IDENTITY, never dropped for scoring under the threshold.

Source of the detector set: the engine's own ``get_loss_config()`` over the pinned
``dataraum-config/entropy/loss.yaml`` (the exact loader the pipeline bands with) —
the simplest robust source, with no recorded fixture to drift out of date.

This is the gated ``calibration/unit`` closure. ``calibration/test_band_grading.py``
is its Tier-3 sibling: the same surface graded on a real run's persisted rows.
"""

from __future__ import annotations

import pytest
from dataraum.entropy.loss import _PRIMARY_SIGNALS, get_loss_config
from dataraum.entropy.models import EntropyObject
from dataraum.entropy.views.readiness_context import assemble_readiness_context

from calibration.band_grading import (
    BAND_RANK,
    NON_READY_BANDS,
    band_measurement,
    detector_loss_signals,
    evidence_signal_detectors,
    loss_table_detectors,
)
from calibration.test_detector_recall import DETECTION_THRESHOLD


def _crossing_value(weight: float, low_upper: float) -> float:
    """A signal value that lifts ``weight·value`` just past the ready→investigate edge.

    Derived from the detector's OWN loss weight relative to the config band edge —
    NOT a hand-set per-detector floor. Capped at 1.0 (every loss weight in the table
    is large enough that this stays a valid [0,1] value).
    """
    return min(1.0, (low_upper + 0.05) / weight)


def test_dat849_signature_is_caught_by_band_missed_by_score() -> None:
    """The exact DAT-849 signature: ``temporal_behavior`` with conflict(=score) 0.0
    and ignorance 0.811 → aggregation ``0.4·0.811 = 0.324`` → ``investigate``.

    This reproduces the live ``fx_rates.rate`` case in ``intent_readiness.yaml``: a
    single uncorroborated stock claim, no conflict, but thin evidence.
    """
    cfg = get_loss_config()
    obj = EntropyObject(
        detector_id="temporal_behavior",
        target="column:fx_rates.rate",
        score=0.0,  # EntropyObjectRecord.score is conflict-only (DAT-457) → conflict 0.0
        evidence=[{"conflict": 0.0, "ignorance": 0.811}],
    )
    measurement = band_measurement(obj, cfg)

    # (a) the band surface catches it — graded by band identity.
    assert measurement.intent_band["aggregation_intent"] == "investigate"
    assert measurement.is_non_ready()
    assert measurement.worst_band() == "investigate"
    # the (conflict, ignorance) the surface exposes is the DAT-849 signature itself,
    # and the risk is the engine's expected loss (0.4 ignorance weight · 0.811).
    assert measurement.ignorance == pytest.approx(0.811)
    assert measurement.intent_risk["aggregation_intent"] == pytest.approx(0.4 * 0.811)

    # (b) a score-only reading at the detection threshold passes it SILENTLY. This
    #     is the DAT-849 blind spot, asserted as a contrast — it neither weakens nor
    #     re-thresholds the score oracle; it documents what score alone cannot see.
    assert measurement.score == 0.0
    assert measurement.conflict == 0.0
    assert measurement.score < DETECTION_THRESHOLD


@pytest.mark.parametrize("detector", sorted(evidence_signal_detectors()))
def test_evidence_driven_band_survives_zero_score(detector: str) -> None:
    """DAT-849 class: for every loss detector with an EVIDENCE (non-primary) signal,
    that signal alone — with ``score=0.0`` — must still drive a non-ready band, and a
    score-only reading must miss it.

    Covers ``null_semantics`` / ``temporal_behavior`` / ``relationship_discovery``
    (ignorance) and ``derived_value`` (formula_conflict / formula_ignorance).
    """
    cfg = get_loss_config()
    low_upper = cfg.readiness_bands["low_upper"]
    signals = detector_loss_signals(detector, cfg)
    signal, weight = max(
        ((s, w) for s, w in signals.items() if s not in _PRIMARY_SIGNALS),
        key=lambda item: item[1],
    )
    value = _crossing_value(weight, low_upper)
    obj = EntropyObject(
        detector_id=detector,
        target=f"column:synthetic.{detector}",
        score=0.0,  # conflict 0.0 — the score oracle sees nothing to detect
        evidence=[{signal: value}],
    )
    measurement = band_measurement(obj, cfg)

    assert measurement.is_non_ready(), (
        f"{detector}: evidence {signal}={value:.3f} with score 0.0 produced only "
        f"{measurement.intent_band} — the band surface failed to grade an "
        f"evidence-driven non-ready outcome (the DAT-849 hole)"
    )
    # The blind spot: this bands non-ready while scoring below the detection threshold.
    # A non-ready measurement is never an abstention (an abstention carries no band),
    # so score is a real float here — the guard narrows the type and states that.
    assert measurement.score is not None and measurement.score < DETECTION_THRESHOLD


@pytest.mark.parametrize("detector", loss_table_detectors())
def test_every_loss_detector_banded_outcome_is_graded(detector: str) -> None:
    """Coverage: EVERY detector in the engine loss table has its banded outcome
    reachable through the graded surface.

    Drives the detector's dominant loss signal (score OR evidence) just past the
    ready→investigate edge and asserts ``band_measurement`` grades it non-ready by
    band identity. Closes the gap where a banded outcome had no oracle at all.
    """
    cfg = get_loss_config()
    low_upper = cfg.readiness_bands["low_upper"]
    signals = detector_loss_signals(detector, cfg)
    assert signals, f"{detector} has no loss weights — not a loss measurement"
    signal, weight = max(signals.items(), key=lambda item: item[1])
    value = _crossing_value(weight, low_upper)

    if signal in _PRIMARY_SIGNALS:
        obj = EntropyObject(
            detector_id=detector, target=f"column:synthetic.{detector}", score=value
        )
    else:
        obj = EntropyObject(
            detector_id=detector,
            target=f"column:synthetic.{detector}",
            score=0.0,
            evidence=[{signal: value}],
        )
    measurement = band_measurement(obj, cfg)

    assert measurement.is_non_ready(), (
        f"{detector}: dominant signal {signal}={value:.3f} did not band non-ready "
        f"({measurement.intent_band}) — its banded outcome is invisible to the surface"
    )


def test_band_surface_matches_engine_readiness_rollup() -> None:
    """Anti-'wrong surface': the per-(target, detector) band surface composes to the
    SAME column band the product shows.

    ``assemble_readiness_context`` (the engine rollup the cockpit reads) must report,
    for a column, the worst band across this module's per-detector measurements — so
    the graded surface is the product's band surface, not a look-alike. The mix here
    is a mild score-only detector (ready on its own) plus the DAT-849 evidence-driven
    one (investigate), so the column band is set by the case score alone never reaches.
    """
    cfg = get_loss_config()
    target = "column:synthetic.mixed"
    objects = [
        EntropyObject(detector_id="business_meaning", target=target, score=0.2),  # -> ready
        EntropyObject(
            detector_id="temporal_behavior",
            target=target,
            score=0.0,
            evidence=[{"ignorance": 0.811}],
        ),  # -> investigate via ignorance
    ]
    ctx = assemble_readiness_context(objects)
    column = ctx.columns[target]

    measurements = [band_measurement(obj, cfg) for obj in objects]
    worst = max((m.worst_band() for m in measurements), key=lambda band: BAND_RANK[band])

    assert column.readiness == worst == "investigate"
    assert column.readiness in NON_READY_BANDS
    # And the score-only detector alone would have left the column ready.
    bm_only = band_measurement(objects[0], cfg)
    assert bm_only.worst_band() == "ready"
