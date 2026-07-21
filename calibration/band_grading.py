"""Band-grading seam — the ``(conflict, ignorance)`` → readiness-band surface (DAT-849).

The score oracles (``test_detector_recall`` / ``test_detector_precision``) grade
``EntropyObjectRecord.score``. But the PRODUCT does not band on the score: it bands
each intent on EXPECTED LOSS,

    risk(intent) = clamp01( Σ weight[signal] · value(signal) )

where a loss weight named ``conflict`` / ``score`` / ``surprise`` scores ``obj.score``
and any OTHER name (``ignorance``, ``formula_conflict``, …) scores the worst matching
value in the evidence JSON (engine ``loss.py`` ``_signal_value``). So a measurement can
score ``0.0`` and still drive an ``investigate`` / ``blocked`` band through ignorance
alone — the exact case no score oracle sees (DAT-849; the live ``fx_rates.rate``
signature: score ``0``, ignorance ``0.811`` → aggregation ``0.4·0.811 = 0.324`` →
``investigate``).

This module exposes that banded surface as first-class GRADED data. It does NOT
reimplement the banding — every ``risk`` / ``band`` here comes from the engine's own
``loss_risk_for_object`` + ``LossConfig.band``, so an oracle built on it grades exactly
what the product shows, not a look-alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dataraum.entropy.loss import (
    _PRIMARY_SIGNALS,
    LossConfig,
    _signal_value,
    get_loss_config,
    loss_risk_for_object,
)
from dataraum.entropy.models import EntropyObject

# Bands a practitioner must not ignore — the outcomes an oracle exists to catch.
NON_READY_BANDS = frozenset({"investigate", "blocked"})

# ready < investigate < blocked. Exported so oracles rank bands from one home.
BAND_RANK = {"ready": 0, "investigate": 1, "blocked": 2}


@dataclass(frozen=True)
class BandedMeasurement:
    """One entropy measurement carrying the loss-band surface the product shows.

    ``score`` is ``EntropyObjectRecord.score``. ``conflict`` is the SAME value: the
    loss table reads the ``conflict`` / ``score`` / ``surprise`` weight off ``obj.score``
    (DAT-457 — score is conflict-only), so ``conflict == score`` by construction, exposed
    under both names for oracle clarity. ``ignorance`` is the engine's own pooling of the
    literal ``ignorance`` evidence signal (``loss.py`` ``_signal_value``) — the
    adjudication ignorance of ``null_semantics`` / ``temporal_behavior`` /
    ``relationship_discovery``. NOTE: ``derived_value`` carries its evidence conflict /
    ignorance under ``formula_conflict`` / ``formula_ignorance``, which this field does
    NOT pool — read those via ``intent_risk`` (which the engine computes over ALL
    signals). ``intent_risk`` / ``intent_band`` are the engine's per-intent expected loss
    and its banding for THIS measurement — never a reimplementation.
    """

    target: str
    detector_id: str
    score: float
    conflict: float
    ignorance: float
    intent_risk: dict[str, float] = field(default_factory=dict)
    intent_band: dict[str, str] = field(default_factory=dict)

    def worst_band(self) -> str:
        """The worst readiness band this measurement drives across its intents."""
        return max(self.intent_band.values(), key=lambda b: BAND_RANK[b], default="ready")

    def is_non_ready(self) -> bool:
        """True if this measurement bands any intent above ``ready``."""
        return any(band in NON_READY_BANDS for band in self.intent_band.values())


def band_measurement(obj: EntropyObject, config: LossConfig | None = None) -> BandedMeasurement:
    """Grade one ``EntropyObject`` on the loss-band surface via the ENGINE's rollup."""
    cfg = config or get_loss_config()
    risk = loss_risk_for_object(obj, cfg)  # engine computation — never reimplemented here
    return BandedMeasurement(
        target=obj.target,
        detector_id=obj.detector_id,
        score=obj.score,
        conflict=obj.score,
        # Engine's own signal reader (not a copy): for the non-primary "ignorance"
        # signal it returns the worst value across the object's evidence.
        ignorance=_signal_value(obj, "ignorance"),
        intent_risk=risk,
        intent_band={intent: cfg.band(value) for intent, value in risk.items()},
    )


def loss_table_detectors(config: LossConfig | None = None) -> list[str]:
    """Every detector the engine's loss table bands on (from ``loss.yaml``)."""
    cfg = config or get_loss_config()
    return sorted(cfg.measurements)


def detector_loss_signals(detector_id: str, config: LossConfig | None = None) -> dict[str, float]:
    """``signal_name`` → its max weight across the detector's intents (``loss.yaml``)."""
    cfg = config or get_loss_config()
    signals: dict[str, float] = {}
    for weights in cfg.measurements.get(detector_id, {}).values():
        for signal, weight in weights.items():
            if weight > signals.get(signal, 0.0):
                signals[signal] = weight
    return signals


def evidence_signal_detectors(config: LossConfig | None = None) -> dict[str, list[str]]:
    """Loss detectors whose band can be driven by an EVIDENCE (non-primary) signal.

    These are the DAT-849-prone measurements: a weight on a signal NOT in the
    engine's ``_PRIMARY_SIGNALS`` scores the evidence JSON, so ``score`` (= conflict)
    can be ``0.0`` while that signal drives a non-ready band — invisible to a score
    oracle. Maps each such detector to its sorted evidence signal names.
    """
    cfg = config or get_loss_config()
    out: dict[str, list[str]] = {}
    for detector in cfg.measurements:
        secondary = sorted(
            signal
            for signal in detector_loss_signals(detector, cfg)
            if signal not in _PRIMARY_SIGNALS
        )
        if secondary:
            out[detector] = secondary
    return out
