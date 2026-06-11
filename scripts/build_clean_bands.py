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
_FLOOR = 0.1

_GRAINS = ("column", "table", "relationship")


def build() -> dict[str, Any]:
    sweeps = sorted(SWEEP_DIR.glob("seed_*.yaml"))
    if len(sweeps) < 2:
        raise SystemExit(f"need >= 2 sweep dumps under {SWEEP_DIR}; found {len(sweeps)}")
    docs = [yaml.safe_load(p.read_text()) for p in sweeps]
    seeds = [d["seed"] for d in docs]

    bands: dict[str, dict[str, dict[str, Any]]] = {g: {} for g in _GRAINS}
    for grain in _GRAINS:
        keys = sorted({k for d in docs for k in d.get(grain, {})})
        for key in keys:
            values = [d[grain][key] for d in docs if key in d.get(grain, {})]
            if max(values) <= _FLOOR:
                continue
            bands[grain][key] = {
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "seen": len(values),
            }

    return {
        "provenance": {
            "source": "A4 clean seed sweep (scripts/probes/a4-seed-sweep driver)",
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    doc = build()
    n = {g: len(doc["bands"][g]) for g in _GRAINS}
    print(f"bands above {_FLOOR}: {n} from seeds {doc['provenance']['seeds']}")
    if args.dry_run:
        print(yaml.safe_dump(doc, sort_keys=False))
        return
    ARTIFACT.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"wrote {ARTIFACT}")


if __name__ == "__main__":
    main()
