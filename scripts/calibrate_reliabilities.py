"""Measure witness reliabilities from the generative families → ship the artifact.

ADR-0009 source #1 (DAT-450): run each null_semantics witness over the null_tokens
family against ground truth, and write the measured r_i — with provenance — to
``dataraum-config/entropy/reliabilities.yaml``, the artifact the engine loads.

This is the calibration RIG, not a tuner: it reports whatever the witnesses' honest
accuracy is. The corpus is realistic, not adversarial: a MAJORITY of distinct-decoy
samples (the common case — genuine-but-unparseable values that smear) plus a
disclosed MINORITY of clustered-decoy stress samples (the rarer case — a recurring
genuine value), so quarantine_clustering's false-positive rate on a clustered
is-value actually enters the estimate instead of being structurally unmeasured. A
held-out corpus (disjoint seeds) scores the proper-scoring diagnostics.

    python scripts/calibrate_reliabilities.py            # measure + print + write
    python scripts/calibrate_reliabilities.py --dry-run  # measure + print only

Deterministic given the seed ranges; the only non-reproducible input is the stamped
date in provenance.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dataraum.entropy.measurements.null_semantics import DEFAULT_RELIABILITIES
from testdata.entropy.families import NullTokenFamilyParams

from calibration.reliability_rig import (
    collect_adjudications,
    estimate_reliabilities,
    opinion_counts,
    per_class_accuracy,
    pooled_brier_with,
    witness_votes,
)

# The shipped artifact the engine consumes (entropy/reliabilities.py loads it).
_ARTIFACT = (
    Path(__file__).resolve().parent.parent
    / "vendor/dataraum-context/packages/dataraum-config/entropy/reliabilities.yaml"
)
_MEASUREMENT_ID = "null_semantics"
_CORPUS_VERSION = "null_tokens-v2"  # v2 adds the disclosed clustered-decoy minority

# Realistic corpus: distinct-decoy majority + a ~20% clustered-decoy minority. The
# minority share is a DISCLOSED composition choice (recurring genuine values are
# real but uncommon), never tuned to a target r.
_NORMAL_FIT = range(0, 400)
_STRESS_FIT = range(20_000, 20_100)
_NORMAL_HOLDOUT = range(10_000, 10_120)
_STRESS_HOLDOUT = range(30_000, 30_030)
_STRESS_PARAMS = NullTokenFamilyParams(decoy_cluster_size=(2, 4))


def _round(values: dict[str, float], ndigits: int = 3) -> dict[str, float]:
    return {k: round(v, ndigits) for k, v in values.items()}


def _round_nested(d: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {k: _round(v, 3) for k, v in d.items()}


def _corpus(normal: range, stress: range) -> list[Any]:
    """Adjudications over the realistic corpus: distinct-decoy + clustered-decoy."""
    return collect_adjudications(normal) + collect_adjudications(stress, params=_STRESS_PARAMS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, do not write the artifact")
    args = parser.parse_args()

    fit_votes = witness_votes(_corpus(_NORMAL_FIT, _STRESS_FIT))
    reliabilities = estimate_reliabilities(fit_votes)
    per_class = per_class_accuracy(fit_votes)
    counts = opinion_counts(fit_votes)

    # Held-out, proper-scoring check (AC4): the measured r must pool BETTER than
    # uniform AND than the placeholder priors on seeds disjoint from the fit corpus.
    holdout = _corpus(_NORMAL_HOLDOUT, _STRESS_HOLDOUT)
    brier_measured = pooled_brier_with(holdout, reliabilities)
    brier_uniform = pooled_brier_with(holdout, dict.fromkeys(reliabilities, 0.5))
    brier_placeholder = pooled_brier_with(holdout, dict(DEFAULT_RELIABILITIES))

    print(f"# reliability calibration — corpus {_CORPUS_VERSION}")
    print(f"fit seeds={len(_NORMAL_FIT)} normal + {len(_STRESS_FIT)} clustered-decoy stress")
    print(f"reliabilities (fit):   {_round(reliabilities)}")
    print(f"per-class:             {_round_nested(per_class)}")
    print(f"opinionated votes:     {counts}")
    print(
        f"held-out pooled brier: measured={brier_measured:.3f}  "
        f"uniform={brier_uniform:.3f}  placeholder={brier_placeholder:.3f}"
    )

    artifact = {
        "provenance": {
            "calibrated": True,
            "source": "eval reliability rig (scripts/calibrate_reliabilities.py), DAT-450",
            "corpus_version": _CORPUS_VERSION,
            "estimator": "Laplace-smoothed accuracy on opinionated votes; abstentions excluded",
            "corpus_composition": f"{len(_NORMAL_FIT)} distinct-decoy + {len(_STRESS_FIT)} "
            "clustered-decoy stress samples (~20% minority, disclosed not tuned)",
            "rows_per_sample": 2000,
            "sample_size_per_witness": counts,
            "per_class_accuracy": _round_nested(per_class),
            "pooled_brier_holdout": round(brier_measured, 4),
            "pooled_brier_holdout_uniform": round(brier_uniform, 4),
            "pooled_brier_holdout_placeholder": round(brier_placeholder, 4),
            "notes": "type_claim votes is-null on everything in failed_examples → it cannot "
            "separate a sentinel from a genuine-but-unparseable value (specificity ~0) → low r, "
            "correctly down-weighted. quarantine_clustering votes is-null on any CLUSTER, so on "
            "the clustered-decoy minority its specificity is < 1 (it mistakes a recurring genuine "
            "value for a sentinel) — now measured, not hidden. Both are witness-design findings "
            "for DAT-457, surfaced not tuned. Conflict C stays weight-robust, so a contested "
            "genuine value still fires investigate via the vocabulary witness's dissent.",
            "date": date.today().isoformat(),
        },
        "witnesses": {_MEASUREMENT_ID: _round(reliabilities, 4)},
    }

    if args.dry_run:
        print("\n--dry-run: artifact NOT written. Would write:\n")
        print(yaml.safe_dump(artifact, sort_keys=False))
        return

    header = _ARTIFACT.read_text().split("\nprovenance:")[0]  # keep the doc comment block
    _ARTIFACT.write_text(header.rstrip() + "\n\n" + yaml.safe_dump(artifact, sort_keys=False))
    print(f"\nwrote {_ARTIFACT}")


if __name__ == "__main__":
    main()
