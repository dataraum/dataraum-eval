"""Detector precision — behavior on clean data, guarded by MEASURED bands.

On clean data (no injections), detector scores reflect baseline data
characteristics, not problems — and a clean emission is a DISTRIBUTION, not a
point: LLM annotation coverage and confidence vary run to run (the A4 seed
sweep measured 145-208 column emissions across four seeds of the same clean
strategy). The guard is therefore a measured band per key
(``calibration/clean_bands.yaml``, built by ``scripts/build_clean_bands.py``
from the sweep dumps), at every grain the rollup scores — column, table,
relationship. A score above its band's max (plus tolerance) is a regression;
a high score with no band is a NEW emission to triage. Scores at or below the
noise floor are uninteresting at any grain.

Regenerate bands only by resweeping (the driver in scripts/probes/ is recreated
per sweep) and rebuilding — never by hand-editing a band to make a run pass.

**These oracles grade the ``clean`` workspace, so they run on the ``clean`` pass
only** (the DAT-797 rule). The scores fixture reads ``clean`` unconditionally, so
without that gate a ``--strategy clean-flat`` pass re-graded a stale ``clean``
workspace and reported a failure that had nothing to do with the strategy under
test — a red run pointing at the wrong corpus is worse than no run.

**Pooled detectors (DAT-826).** A per-key band asks "did THIS column score above
what it scored during the sweep". That is the right question for a deterministic
statistic and the wrong one for an LLM confidence: ``business_meaning`` is
``1 - naming_confidence``, and the model emits confidence on a coarse grid — the
27 swept keys carry exactly three distinct maxima (0.15 / 0.20 / 0.25, i.e.
confidence 0.85 / 0.80 / 0.75). Which well-named clean column lands on which grid
point rotates run to run (the sweep notes say date/reference/amount "shuffle every
run"). So a per-key band for that detector measures which column the LLM hedged
on, not whether the detector is right, and it fails at 0.300 on a key swept at
0.20 while passing at 0.300 on a key swept at 0.25 — pure assignment luck.

The precision claim that actually has content is population-level: on clean data
every column is well named, so NO column should look unnamed. That is asserted as
a pooled ceiling over the whole clean population, which is the pooling the method
doc prescribes for non-determinism (never an override, never a per-point
threshold). The recall side already treats this detector the same way, via
``LLM_NONDETERMINISTIC`` + ``xfail(strict=False)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from calibration.conftest import DetectorScores

EVAL_ROOT = Path(__file__).parent.parent
BANDS_PATH = EVAL_ROOT / "calibration" / "clean_bands.yaml"

# Scores at or below this are uninteresting — don't track them
NOISE_FLOOR = 0.15

# Detectors whose score IS a live LLM confidence, graded as a POOLED population
# ceiling instead of per-key bands (see the module docstring). Per-detector
# ceiling = the highest max the sweep measured for it across all keys.
POOLED_LLM_DETECTORS = {"business_meaning"}

# Band max + this much is a regression (sampling slack atop a 4-seed band).
BAND_TOLERANCE = 0.05


def _load_bands_doc() -> dict[str, Any]:
    if not BANDS_PATH.exists():
        pytest.skip(
            f"No measured bands at {BANDS_PATH} — run a clean seed sweep and "
            "scripts/build_clean_bands.py."
        )
    result: dict[str, Any] = yaml.safe_load(BANDS_PATH.read_text()) or {}
    return result


def _load_bands() -> dict[str, dict[str, dict[str, Any]]]:
    bands: dict[str, dict[str, dict[str, Any]]] = _load_bands_doc().get("bands", {})
    return bands


def _scored_keys(scores: DetectorScores) -> dict[str, dict[str, tuple[str, float]]]:
    """Per grain: band key -> (detector, score), matching the sweep dump's keys."""
    return {
        "column": {f"{t}.{c}:{d}": (d, s) for (t, c, d), s in scores.column.items()},
        "table": {f"{t}:{d}": (d, s) for (t, d), s in scores.table.items()},
        "relationship": {f"{t}.{c}:{d}": (d, s) for (t, c, d), s in scores.relationship.items()},
    }


@pytest.fixture
def clean_only(strategy_name: str) -> None:
    """Grade the clean baseline on the clean pass only (DAT-797).

    ``clean_detector_scores`` reads the ``clean`` workspace unconditionally, so on
    any other ``--strategy`` these oracles re-grade a stale clean run and report a
    failure attributed to the wrong corpus. Scoping is the fix; pointing the
    fixture at the strategy under test is not — a clean BASELINE band means
    nothing against an injected or differently-shaped corpus.
    """
    if strategy_name != "clean":
        pytest.skip(
            f"clean-baseline oracle — runs on the 'clean' pass only (got {strategy_name!r})"
        )


def _pooled_ceiling(bands: dict[str, dict[str, dict[str, Any]]], detector: str) -> float | None:
    """The highest max the sweep measured for ``detector``, across every key/grain."""
    maxima = [
        float(band["max"])
        for entries in bands.values()
        for key, band in entries.items()
        if key.endswith(f":{detector}")
    ]
    return max(maxima) if maxima else None


def test_clean_scores_within_measured_bands(
    clean_detector_scores: DetectorScores,
    clean_only: None,
) -> None:
    """Every clean score above its floor sits within its measured band (+tolerance).

    Covers ALL scored grains — the old captured baseline guarded column grain
    only, leaving dimension_coverage (table) and the relationship scalars
    unguarded (B2 finding). Detectors in ``POOLED_LLM_DETECTORS`` are graded by
    the pooled test below instead: their per-key band tracks a rotating LLM
    assignment, not the detector.
    """
    bands = _load_bands()
    regressions: list[str] = []
    new_high: list[str] = []

    for grain, keyed in _scored_keys(clean_detector_scores).items():
        grain_bands = bands.get(grain, {})
        for key, (detector, score) in sorted(keyed.items()):
            if detector in POOLED_LLM_DETECTORS or score <= NOISE_FLOOR:
                continue
            band = grain_bands.get(key)
            if band is None:
                new_high.append(f"  [{grain}] {key}: {score:.3f} (NEW — no band)")
            elif score > float(band["max"]) + BAND_TOLERANCE:
                regressions.append(
                    f"  [{grain}] {key}: {score:.3f} > band [{band['min']:.3f}, "
                    f"{band['max']:.3f}] + {BAND_TOLERANCE} (seen {band['seen']}x)"
                )

    lines = []
    if regressions:
        lines.append(f"{len(regressions)} regressions above measured bands:")
        lines.extend(regressions)
    if new_high:
        lines.append(f"{len(new_high)} new high scores with no measured band:")
        lines.extend(new_high)
    if lines:
        lines.append("")
        lines.append(
            "If a detector or spec change makes these expected, resweep (clean at "
            ">= 2 seeds) and rebuild: uv run python scripts/build_clean_bands.py. "
            "Never hand-edit a band."
        )
        raise AssertionError("\n".join(lines))


def test_pooled_llm_detectors_below_measured_ceiling(
    clean_detector_scores: DetectorScores,
    clean_only: None,
) -> None:
    """No clean column looks unnamed — the population claim, not a per-column one.

    On clean data every column is legitimately named, so the content of the
    precision claim is that the LLM stays confident about ALL of them. Asserted
    as the pooled maximum against the highest max the sweep measured for the
    detector: it catches the regression that matters (the model starts hedging
    harder than it ever did on clean data) without pinning which column it hedges
    on, which rotates every run and is not a property of the detector.
    """
    bands = _load_bands()
    breaches: list[str] = []

    for detector in sorted(POOLED_LLM_DETECTORS):
        ceiling = _pooled_ceiling(bands, detector)
        if ceiling is None:
            continue
        scored = [
            (grain, key, score)
            for grain, keyed in _scored_keys(clean_detector_scores).items()
            for key, (d, score) in keyed.items()
            if d == detector
        ]
        if not scored:
            continue
        grain, key, worst = max(scored, key=lambda row: row[2])
        print(
            f"\n[{detector}] {len(scored)} clean emissions, "
            f"worst {worst:.3f} ({grain} {key}) vs measured ceiling {ceiling:.3f}"
        )
        # Compare at the MEASUREMENT's resolution, not IEEE754's. The score is
        # ``1 - confidence`` over a 2-decimal LLM confidence, so it lands on a
        # coarse grid; ``1 - 0.7`` is 0.30000000000000004 while ``0.25 + 0.05`` is
        # exactly 0.3, and a raw ``>`` fails a run that sits precisely ON the
        # allowed boundary. Rounding to 4dp is far below the grid and far above
        # float noise — it removes an artifact, it does not widen the criterion.
        if round(worst, 4) > round(ceiling + BAND_TOLERANCE, 4):
            breaches.append(
                f"  {detector}: worst clean emission {worst:.3f} ({grain} {key}) "
                f"> measured ceiling {ceiling:.3f} + {BAND_TOLERANCE} "
                f"over {len(scored)} columns"
            )

    assert not breaches, (
        "LLM-confidence detector(s) hedging harder on clean data than the sweep "
        "ever measured — the model is less sure about well-named columns than it "
        "was, which is a real precision regression:\n" + "\n".join(breaches)
    )


def test_stable_clean_emitters_still_emit(
    clean_detector_scores: DetectorScores,
    clean_only: None,
) -> None:
    """RECALL guard: a key every sweep seed emitted must not go silent.

    The bands test above catches scores going UP; this catches the invisible
    failure — a detector that stops emitting entirely (wiring break, phase
    drop, loader regression) looks like a perfectly quiet clean run. False
    positives are interpretable by a human or an agent; false negatives are
    invisible — so disappearance of a stable emitter fails loudly (optimize
    recall first; Philipp, 2026-06-11). Keys emitted only intermittently
    across the sweep (seen < n_seeds: LLM coverage wobble) are exempt.
    """
    doc = _load_bands_doc()
    n_seeds = len(doc.get("provenance", {}).get("seeds", []))
    if not n_seeds:
        pytest.skip("bands artifact carries no seed provenance")

    scored = {grain: set(keys) for grain, keys in _scored_keys(clean_detector_scores).items()}
    silent: list[str] = []
    for grain, entries in doc.get("bands", {}).items():
        for key, band in sorted(entries.items()):
            if band.get("seen") == n_seeds and key not in scored.get(grain, set()):
                silent.append(
                    f"  [{grain}] {key}: emitted on all {n_seeds} sweep seeds "
                    f"(band [{band['min']:.3f}, {band['max']:.3f}]) — now ABSENT"
                )
    assert not silent, (
        f"{len(silent)} stable clean emitters went silent — a wiring/loader break "
        "is the false-negative machine:\n" + "\n".join(silent)
    )


def test_clean_average_below_threshold(
    clean_pipeline_scores: dict[tuple[str, str, str], float],
    clean_only: None,
) -> None:
    """Average column score across clean data should be low.

    This catches systematic drift where many detectors start scoring higher.
    """
    if not clean_pipeline_scores:
        return

    avg = sum(clean_pipeline_scores.values()) / len(clean_pipeline_scores)
    assert avg < 0.15, f"Average clean score {avg:.3f} too high — detectors are noisy"
