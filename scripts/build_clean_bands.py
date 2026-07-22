"""Build measured clean score BANDS from a seed sweep — the A4 rig.

Reads every ``output/seed_sweep/seed_*.yaml`` (written by the sweep driver:
generate clean at several seeds, run the pipeline, dump per-grain scores) and
writes ``calibration/clean_bands.yaml``: per grain, per key, the observed
[min, max] across seeds plus a presence count. The bands REPLACE the captured
single-run clean_baseline.yaml — a clean emission is a distribution (LLM
annotation coverage and confidence vary run to run), so the regression guard
must be a measured band, not one captured point.

This is a rig, not a probe: rerun it whenever the sweep is redone (detector
changes, spec fixes that should tighten a band). It reports what it saw;
it never filters or clips.

    uv run python scripts/build_clean_bands.py            # build + write
    uv run python scripts/build_clean_bands.py --dry-run  # print only
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).resolve().parent.parent
SWEEP_DIR = EVAL_ROOT / "output" / "seed_sweep"
ARTIFACT = EVAL_ROOT / "calibration" / "clean_bands.yaml"

# Bands below this are uninteresting at every grain — don't record them.
# (Matches the precision test's NOISE_FLOOR; per-detector floors apply there.)
# Recording threshold ONLY — the degeneracy check below runs independent of it.
_FLOOR = 0.1

_GRAINS = ("column", "table", "relationship")

# Degeneracy lint: a CONTINUOUS statistic must vary across reseeded clean data —
# min == max over >= 2 seeds means the detector is not reading the data (constant
# fallback / wiring bug). Both DAT-602 round-1 bugs sat in this file as exactly
# that signature while green: temporal_behavior 0.5127 x3 (mis-wired) and
# unit_entropy 1.0 x3 (the DAT-647 false-block). Detectors whose clean score is
# discrete by design are exempt — extend ONLY with the reason stated inline.
_DISCRETE_BY_DESIGN = frozenset(
    {
        "unit_source",  # binary 0/1 catalogue fact (unit resolvable or not)
        # LLM step-map over SEED-INVARIANT inputs: the score quantizes annotation
        # facts (has_description, confidence buckets) about the column NAME —
        # names and schema don't vary across seeds, so constancy is expected.
        "business_meaning",
        # Pooled conflict C over witness distributions that SATURATE on clean
        # pairs (containment ceiling 1.0, quantized LLM confidence) → C is a pure
        # function of identical inputs across seeds. Seed variation enters only
        # under violation, where the recall ordering leg guards it (FK-0008
        # scores 0.2 on the 20% orphan injection while clean pairs sit constant).
        "relationship_discovery",
    }
)


def build_from_docs(docs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Build the bands document from sweep dumps; also return degenerate keys.

    Degenerate = zero-width on raw (unrounded) values at a NONZERO constant
    across >= 2 seeds for a detector not in ``_DISCRETE_BY_DESIGN``. A constant
    0.0 is the correct clean baseline (the detector read the data and found no
    entropy), never degeneracy.
    """
    seeds = [d["seed"] for d in docs]

    bands: dict[str, dict[str, dict[str, Any]]] = {g: {} for g in _GRAINS}
    degenerate: list[str] = []
    for grain in _GRAINS:
        keys = sorted({k for d in docs for k in d.get(grain, {})})
        # Per-detector census across ALL its keys × seeds, for the degeneracy
        # lint below. Degeneracy is a property of the DETECTOR (is it reading the
        # data at all?), not of a single key: a detector that varies across keys
        # is alive, and a lone key that is constant across seeds is a
        # SEED-INVARIANT input (a fixed dimension's null_ratio, a fixed date
        # grid's temporal_behavior), not a wiring bug. Keying the flag per-key
        # false-flagged exactly those (DAT-853 validation, 2026-07-22).
        detector_vals: dict[str, set[float]] = {}
        detector_keys: dict[str, list[str]] = {}
        detector_obs: dict[str, int] = {}
        for key in keys:
            values = [d[grain][key] for d in docs if key in d.get(grain, {})]
            # Floor gates RECORDING only — a key at or below it never enters the
            # bands artifact, but its values still feed the degeneracy census: a
            # detector stuck at/under the floor (join_path_determinism's 0.100 on
            # every relationship) is exactly the wiring bug this lint exists to
            # catch, and skipping it below defeated the purpose.
            if max(values) > _FLOOR:
                bands[grain][key] = {
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "seen": len(values),
                }
            detector = key.rsplit(":", 1)[-1]
            detector_vals.setdefault(detector, set()).update(values)
            detector_keys.setdefault(detector, []).append(key)
            detector_obs[detector] = detector_obs.get(detector, 0) + len(values)
        # Degenerate = a detector STUCK at a single NONZERO value across ALL its
        # keys and seeds — it is not reading the data (join_path_determinism's
        # 0.1 everywhere, temporal_behavior's 0.5127, the unit_entropy 1.0
        # false-block). NOT flagged, each learned the expensive way: a detector
        # that varies across keys (alive), a constant 0.0 (the correct clean
        # baseline — a detector that read the data and found no entropy, never a
        # wiring bug), a single observation (cannot witness), a discrete-by-design
        # detector.
        for detector, vals in sorted(detector_vals.items()):
            if (
                detector_obs[detector] >= 2
                and len(vals) == 1
                and next(iter(vals)) > 0.0
                and detector not in _DISCRETE_BY_DESIGN
            ):
                keys_str = ", ".join(sorted(detector_keys[detector]))
                degenerate.append(
                    f"[{grain}] {detector}: constant {next(iter(vals))} across all "
                    f"keys/seeds ({keys_str})"
                )

    doc = {
        "provenance": {
            # The original `scripts/probes/a4-seed-sweep` driver was deleted as a
            # probe; `scripts/sweep_clean_seeds.py` replaced it as a rig. Naming a
            # script that no longer exists made the artifact unreproducible to read.
            "source": "clean seed sweep (scripts/sweep_clean_seeds.py)",
            "seeds": seeds,
            "date": date.today().isoformat(),
            "notes": (
                "Observed [min, max] per key across seeds; 'seen' < len(seeds) means "
                "the key was not emitted on every run (LLM annotation coverage varies "
                "— normal, not a regression). Wide bands document real run-to-run "
                "variance at sweep time; a spec/detector fix that should tighten one "
                "is proven by resweeping and rebuilding, never by hand-editing."
            ),
        },
        "bands": bands,
    }
    return doc, degenerate


def build() -> tuple[dict[str, Any], list[str]]:
    sweeps = sorted(SWEEP_DIR.glob("seed_*.yaml"))
    if len(sweeps) < 2:
        raise SystemExit(f"need >= 2 sweep dumps under {SWEEP_DIR}; found {len(sweeps)}")
    docs = [yaml.safe_load(p.read_text()) for p in sweeps]
    return build_from_docs(docs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    doc, degenerate = build()
    n = {g: len(doc["bands"][g]) for g in _GRAINS}
    print(f"bands above {_FLOOR}: {n} from seeds {doc['provenance']['seeds']}")
    if args.dry_run:
        print(yaml.safe_dump(doc, sort_keys=False))
    if degenerate:
        print("DEGENERATE bands — constant across seeds; the detector is not")
        print("reading data variation (the temporal_behavior/unit_entropy bug signature):")
        for line in degenerate:
            print(f"  {line}")
        raise SystemExit(
            "refusing to bless degenerate bands: fix the detector, or if the score is "
            "discrete by design, add it to _DISCRETE_BY_DESIGN with the reason inline"
        )
    if args.dry_run:
        return
    ARTIFACT.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"wrote {ARTIFACT}")


if __name__ == "__main__":
    main()
