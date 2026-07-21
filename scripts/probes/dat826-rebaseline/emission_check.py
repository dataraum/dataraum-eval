"""Did a detector that vanished from the bands IMPROVE, or go SILENT? (DAT-826)

The bands artifact only records keys scoring above 0.1, so a detector dropping out
is ambiguous: it either now scores low (a precision win) or stopped emitting
(a wiring break — the invisible failure the repo optimizes against). The raw sweep
dumps carry every emitted key at any score, so they settle it.

    uv run python scripts/probes/dat826-rebaseline/emission_check.py temporal_behavior unit_source
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).resolve().parents[3]
SWEEP_DIR = EVAL_ROOT / "output" / "seed_sweep"


def main(detectors: list[str]) -> None:
    docs = [yaml.safe_load(p.read_text()) for p in sorted(SWEEP_DIR.glob("seed_*.yaml"))]
    for det in detectors:
        print(f"\n=== {det} ===")
        for doc in docs:
            hits: list[tuple[str, float]] = []
            for grain in ("column", "table", "relationship"):
                for key, score in (doc.get(grain) or {}).items():
                    if key.rsplit(":", 1)[-1] == det:
                        hits.append((f"{grain}/{key}", float(score)))
            scores = [s for _, s in hits]
            if not hits:
                print(f"  seed {doc['seed']}: NOT EMITTED — 0 keys  <-- SILENT")
                continue
            top = sorted(hits, key=lambda h: h[1], reverse=True)[:3]
            print(
                f"  seed {doc['seed']}: {len(hits)} keys emitted, "
                f"max {max(scores):.3f}, mean {sum(scores) / len(scores):.3f}"
            )
            for name, score in top:
                print(f"      {score:.3f}  {name}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("detectors", nargs="+")
    main(**vars(p.parse_args()))
