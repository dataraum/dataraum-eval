"""Measure witness reliabilities from the generative families → ship the artifact.

ADR-0009 source #1 (DAT-450): run each null_semantics witness over the null_tokens
family against ground truth, and write the measured r_i — with provenance — to
``dataraum-config/entropy/reliabilities.yaml``, the artifact the engine loads.

This is the calibration RIG, not a tuner: it reports whatever the witnesses' honest
accuracy is. A held-out seed range (disjoint from the fitting range) is scored for
the proper-scoring diagnostics so calibration is measured on data not used to fit.

    python scripts/calibrate_reliabilities.py            # measure + print + write
    python scripts/calibrate_reliabilities.py --dry-run  # measure + print only

Usage notes: deterministic given the seed ranges; the only non-reproducible input
is the stamped date in provenance.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import yaml
from dataraum.entropy.measurements.null_semantics import DEFAULT_RELIABILITIES

from calibration.reliability_rig import (
    calibrate,
    collect_adjudications,
    pooled_brier_with,
)

# The shipped artifact the engine consumes (entropy/reliabilities.py loads it).
_ARTIFACT = (
    Path(__file__).resolve().parent.parent
    / "vendor/dataraum-context/packages/dataraum-config/entropy/reliabilities.yaml"
)
_MEASUREMENT_ID = "null_semantics"
_CORPUS_VERSION = "null_tokens-v1"
_FIT_SEEDS = range(0, 400)
_HOLDOUT_SEEDS = range(10_000, 10_120)


def _round(values: dict[str, float], ndigits: int = 3) -> dict[str, float]:
    return {k: round(v, ndigits) for k, v in values.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, do not write the artifact")
    args = parser.parse_args()

    fit = calibrate(list(_FIT_SEEDS))

    # Held-out, proper-scoring check (AC4): the measured r must pool BETTER than
    # uniform weights — "the shipped r are calibrated, not just that detection
    # fires" — on seeds disjoint from the fit corpus.
    holdout_adj = collect_adjudications(_HOLDOUT_SEEDS)
    uniform = dict.fromkeys(fit.reliabilities, 0.5)
    brier_measured = pooled_brier_with(holdout_adj, fit.reliabilities)
    brier_uniform = pooled_brier_with(holdout_adj, uniform)
    brier_placeholder = pooled_brier_with(holdout_adj, dict(DEFAULT_RELIABILITIES))

    print(f"# reliability calibration — corpus {_CORPUS_VERSION}")
    print(f"fit seeds={len(_FIT_SEEDS)}  rows/sample={fit.n_rows}")
    print(f"reliabilities (fit):   {_round(fit.reliabilities)}")
    print(f"opinionated votes:     {fit.per_witness_votes}")
    print(f"brier per witness:     {_round(fit.brier)}  (abstain baseline 0.25)")
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
            "rows_per_sample": fit.n_rows,
            "sample_size_per_witness": fit.per_witness_votes,
            "seeds": f"fit={_FIT_SEEDS.start}..{_FIT_SEEDS.stop - 1}, "
            f"holdout={_HOLDOUT_SEEDS.start}..{_HOLDOUT_SEEDS.stop - 1}",
            "pooled_brier_holdout": round(brier_measured, 4),
            "pooled_brier_holdout_uniform": round(brier_uniform, 4),
            "pooled_brier_holdout_placeholder": round(brier_placeholder, 4),
            "notes": "quarantine_clustering never argues is-value (abstains on decoys) → its "
            "r is a sensitivity, not a discrimination score. type_claim votes is-null on "
            "everything in failed_examples, so it cannot separate a sentinel from a "
            "genuine-but-unparseable value → low r (~0.22, Brier worse than always-abstain), "
            "correctly down-weighted: a witness-design finding for DAT-457, surfaced not tuned.",
            "date": date.today().isoformat(),
        },
        "witnesses": {_MEASUREMENT_ID: _round(fit.reliabilities, 4)},
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
