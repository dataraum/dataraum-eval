"""Stage a Tier-B (wild) corpus for the real pipeline, and derive its truth.

Tier B is the external-corpus half of the corpus policy (`entropy_eval_architecture.md`):
real databases, **structural truth only**, graded as a scoreboard and never a
build-break. Its job is the one thing the synthetic corpus structurally cannot do —
falsify "we're great." A schema we invented, which our own agents parse cleanly, mainly
proves we are good at writing schemas for ourselves.

Two steps, both mechanical:

1. **Stage** — copy `corpora/relbench/<ds>/tables/*.parquet` flat into `data/<name>/`.
   Flat because `runner._upload_sources_to_lake` iterates one level and turns each file
   into its own content-keyed source; `schema.json` is deliberately left behind (`.json`
   is a data suffix, so it would ingest as a spurious ninth table).

2. **Derive truth** — `schema.json` → `data/<name>/metadata_truth.yaml`, the per-run
   seam `conftest.metadata_truth` already prefers over the committed finance fixture.
   So the existing oracles grade a foreign corpus with no new assertion grammar.

**Declared structure only.** Two sections, both read straight off RelBench's own
metadata with no inference:

* `relationships` ← `fkeys` (the FK a real schema declares about itself)
* `semantic_roles.timestamp` ← `time_col`

Everything else is omitted on purpose. Table roles, stock/flow, cycles and business
concepts would be *our* reading of someone else's schema, not their declared truth —
inventing them here would grade the engine against a guess and call it ground truth.
Those oracles stand down, and the run summary now names them as skipped rather than
passing in silence. RelBench's task labels (churn/LTV) are ML labels and are never
metadata truth.

    uv run python scripts/stage_wild_corpus.py rel-f1
    uv run python -m calibration.runner rel-f1 --pipeline-only
    uv run pytest calibration/ --strategy rel-f1 -q
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).resolve().parent.parent
CORPORA_DIR = EVAL_ROOT / "corpora" / "relbench"
DATA_DIR = EVAL_ROOT / "data"


def derive_truth(schema: dict[str, Any], *, vertical: str) -> dict[str, Any]:
    """RelBench `schema.json` → the declared-structure subset of metadata_truth."""
    relationships: list[dict[str, Any]] = []
    timestamps: list[str] = []

    # Case-fold to match the engine's typed catalog. RelBench declares camelCase
    # (`circuitId`); the engine normalizes column names to lowercase at typing, so
    # truth authored verbatim mismatches every edge and reads as total recall
    # failure. Measured: 0/13 before, 13/13 after, on identical run data.
    def norm(name: str) -> str:
        return name.lower()

    for table, spec in sorted(schema.items()):
        for fk_col, ref_table in sorted((spec.get("fkeys") or {}).items()):
            ref_pkey = (schema.get(ref_table) or {}).get("pkey")
            if not ref_pkey:
                # A declared FK whose target has no declared pkey is not a gradeable
                # edge — skip it rather than invent the target column.
                continue
            relationships.append(
                {"from": f"{norm(table)}.{norm(fk_col)}",
                 "to": f"{norm(ref_table)}.{norm(ref_pkey)}",
                 "direction_reliable": True}
            )
        if spec.get("time_col"):
            timestamps.append(f"{norm(table)}.{norm(spec['time_col'])}")

    return {
        "vertical": vertical,
        "tier": "wild",  # structural truth only — scoreboard, never a build-break
        "relationships": relationships,
        "semantic_roles": {"timestamp": sorted(timestamps)},
    }


def stage(dataset: str, *, name: str | None = None) -> Path:
    src = CORPORA_DIR / dataset
    if not src.exists():
        raise SystemExit(
            f"{src} missing — fetch it first:\n"
            f"  uv run --with relbench --with pandas --with pyarrow python "
            f"scripts/probes/dat757-relbench/fetch_export.py {dataset}"
        )
    schema = json.loads((src / "schema.json").read_text())

    dest = DATA_DIR / (name or dataset)
    dest.mkdir(parents=True, exist_ok=True)
    for parquet in sorted((src / "tables").glob("*.parquet")):
        shutil.copy2(parquet, dest / parquet.name)

    truth = derive_truth(schema, vertical=dataset)
    (dest / "metadata_truth.yaml").write_text(yaml.safe_dump(truth, sort_keys=False))

    n_rows = sum(s.get("n_rows", 0) for s in schema.values())
    print(f"[wild] staged {dataset} → {dest}")
    print(f"[wild]   {len(schema)} tables, {n_rows:,} rows")
    print(f"[wild]   truth: {len(truth['relationships'])} declared FKs, "
          f"{len(truth['semantic_roles']['timestamp'])} declared time columns")
    print("[wild]   omitted (not declared by the corpus): table_roles, stock_flow, "
          "cycles, business_concepts, bus_matrix — those oracles will SKIP")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", help="RelBench dataset under corpora/relbench/ (e.g. rel-f1)")
    parser.add_argument("--name", help="Strategy name to stage as (default: the dataset name)")
    stage(**vars(parser.parse_args()))
