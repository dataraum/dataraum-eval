"""Band-grading oracle (Tier-3) — the (conflict, ignorance) surface is graded on a
real run, not just the score (DAT-849).

The score oracles (``test_detector_recall`` / ``test_detector_precision``) grade
``EntropyObjectRecord.score``. The PRODUCT bands each intent on expected loss over
``(conflict, ignorance)`` — so a measurement can score ``0.0`` yet drive an
``investigate`` / ``blocked`` band through ignorance alone, a banded outcome no
score oracle sees. This oracle closes that hole on the LIVE run, in both directions:

  * every non-ready column band the engine's readiness rollup reports
    (``intent_readiness``) must be explained by a loss measurement in the graded
    band surface (``banded_measurements``) — a band the surface cannot see IS the
    DAT-849 bug;
  * every under-threshold non-ready measurement in the graded surface (the DAT-849
    class: banded through ignorance, invisible to score) must be corroborated by the
    engine's column readiness — the graded surface may not band non-ready where the
    rollup does not.

Because the two fixtures re-assemble from the SAME head-resolved rows through the
engine's loss functions, these checks pass when the two loaders agree and FAIL when
they diverge (a dropped signal, different head resolution, different evidence
handling) — the fixture-layer regression this lane must not let through. (A stronger,
fully-independent cross-check would read the persisted ``entropy_readiness`` rows the
cockpit serves; that is a follow-up, not this lane — the neighbouring
``test_intent_readiness`` re-assembles the same way.)

Tier: reads the workspace's persisted rows through the session-scoped
``banded_measurements`` / ``intent_readiness`` fixtures, which SKIP when the strategy
has no completed run (``_require_pipeline_run`` — the neighbouring Tier-3 convention).
The deterministic proof that the surface works at all lives in
``calibration/unit/test_band_grading.py`` and runs without docker. Scope is column
grain (``intent_readiness``); the relationship-grain band surface is graded by
``test_intent_readiness`` (grain: relationship) and the deterministic sweep over
``relationship_discovery`` / ``relationship_entropy``.
"""

from __future__ import annotations

import pytest

from calibration.band_grading import NON_READY_BANDS, BandedMeasurement
from calibration.conftest import _strip_source_prefix
from calibration.test_detector_recall import DETECTION_THRESHOLD


def _non_ready_intents_by_column(
    measurements: list[BandedMeasurement],
) -> dict[tuple[str, str], set[str]]:
    """(table, column) → the set of intents this run bands non-ready, per the graded
    surface.

    Only column-target measurements. Keys are derived exactly as
    ``conftest._load_intent_readiness`` derives ``intent_readiness`` keys — the
    source prefix stripped from the table, the column taken as stored (the pipeline
    already lowercases column names on import) — so the two sides join on identical
    keys, not on a coincidence.
    """
    by_column: dict[tuple[str, str], set[str]] = {}
    for measurement in measurements:
        if not measurement.target.startswith("column:"):
            continue
        ref = measurement.target.removeprefix("column:")
        if "." not in ref:
            continue
        table, column = ref.split(".", 1)
        key = (_strip_source_prefix(table), column)
        for intent, band in measurement.intent_band.items():
            if band in NON_READY_BANDS:
                by_column.setdefault(key, set()).add(intent)
    return by_column


def test_banded_surface_covers_every_engine_non_ready_band(
    banded_measurements: list[BandedMeasurement],
    intent_readiness: dict[tuple[str, str], dict[str, str]],
) -> None:
    """Every non-ready column band the engine reports is graded by the band surface.

    ``intent_readiness`` is the engine's per-column readiness (the cockpit reads the
    same rollup); ``banded_measurements`` is the per-(target, detector) graded
    surface DAT-849 adds. A non-ready band in the former with no non-ready
    measurement for that column in the latter means a banded outcome fell through
    the graded surface — the exact hole score oracles leave open.
    """
    if not banded_measurements:
        pytest.skip("run produced no loss-table measurements to band-grade")

    engine_non_ready = {
        (key, intent)
        for key, intents in intent_readiness.items()
        for intent, band in intents.items()
        if band in NON_READY_BANDS
    }
    if not engine_non_ready:
        pytest.skip("this run has no non-ready column band — nothing for the surface to cover")

    graded = _non_ready_intents_by_column(banded_measurements)
    missing = [
        f"  {key[0]}.{key[1]} {intent} — not in the graded band surface"
        for key, intent in sorted(engine_non_ready)
        if intent not in graded.get(key, set())
    ]

    assert not missing, (
        "the engine bands these column intents non-ready but the graded (conflict, "
        "ignorance) surface does not see them (DAT-849 hole):\n" + "\n".join(missing)
    )


def test_zero_score_bands_are_corroborated_by_column_readiness(
    banded_measurements: list[BandedMeasurement],
    intent_readiness: dict[tuple[str, str], dict[str, str]],
) -> None:
    """The DAT-849 class ON REAL DATA: measurements that band non-ready while scoring
    below ``DETECTION_THRESHOLD`` must be corroborated by the engine's column
    readiness for the same intent.

    These are exactly the rows a score oracle discards ("scored under threshold =
    nothing detected"). Each such column measurement's non-ready intents must be a
    subset of what ``intent_readiness`` bands non-ready for that column — an equality
    that holds when the graded surface and the rollup agree (the rollup max-pools per
    column, so any per-measurement non-ready intent must survive) and FAILS if the
    two loaders diverge. If this run produced none, the class is not exercised — skip
    honestly rather than pass vacuously (the neighbouring oracle-coverage convention).
    """
    if not banded_measurements:
        pytest.skip("run produced no loss-table measurements to band-grade")

    zero_score_non_ready = [
        measurement
        for measurement in banded_measurements
        if measurement.target.startswith("column:")
        and measurement.is_non_ready()
        and measurement.score is not None  # non-ready ⇒ measured (never an abstention)
        and measurement.score < DETECTION_THRESHOLD
    ]
    if not zero_score_non_ready:
        pytest.skip(
            "no under-threshold non-ready column measurement this run — the DAT-849 "
            "class (score-invisible band) was not exercised"
        )

    mismatches: list[str] = []
    for measurement in zero_score_non_ready:
        ref = measurement.target.removeprefix("column:")
        if "." not in ref:
            continue
        table, column = ref.split(".", 1)
        key = (_strip_source_prefix(table), column)
        engine = intent_readiness.get(key, {})
        surface_non_ready = {
            intent for intent, band in measurement.intent_band.items() if band in NON_READY_BANDS
        }
        engine_non_ready = {intent for intent, band in engine.items() if band in NON_READY_BANDS}
        if not surface_non_ready <= engine_non_ready:
            mismatches.append(
                f"  {key[0]}.{key[1]} {measurement.detector_id} (score {measurement.score:.3f}): "
                f"band surface {sorted(surface_non_ready)} not corroborated by column "
                f"readiness {sorted(engine_non_ready)}"
            )

    assert not mismatches, (
        "a score-under-threshold measurement bands non-ready but the engine's column "
        "readiness does not corroborate it (graded surface diverged from the rollup):\n"
        + "\n".join(mismatches)
    )
