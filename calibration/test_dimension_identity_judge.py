"""DAT-762 lane acceptance, component 2: the judge leg (LLM, fixture-driven).

Runs the routed scorecard cells through the ENGINE's DimensionIdentityJudge —
Phase A's prompts, tool schemas, and repair path, not the probe's ad-hoc
judge — and grades verdicts against the pre-registered truth:

- veto leg (HARD floor): every routed cell is one where the stack's assertion
  contradicts truth (that is what the routing classes ARE), so the correct
  verdict is VETO on all of them. Measured names-only performance: 8-9/9.
  Asserted >= 7/9 (LLM wobble allowed, still far above chance); per-cell
  verdicts printed, never overridden.
- conform leg (HARD on the costly error): no false friend (L) pair may
  CONFORM — a false merge silently corrupts cross-fact aggregation. K
  (disjoint conform) is reported, not asserted (measured weak: C2 1/2, K2
  pre-flagged SOFT; no meanings exist for RelBench columns, so the judge
  works names-only and abstains more).

No pipeline, no docker — the engine as a library + the frozen fixture +
real LLM calls (~14/rep). Marked ``llm``; skips without an API key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip(
    "dataraum.analysis.hierarchies.routing",
    reason="engine has no dimension-identity lane yet (pre-DAT-762)",
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures/dimension_identity_cells.json"


def _judge() -> Any:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("no ANTHROPIC_API_KEY — the judge leg needs real LLM calls")

    # The judge is config + LLM only, but the engine's fail-loud Settings
    # validates the full substrate env at import — satisfy it from the stack
    # constants WITHOUT bringing up docker (no PG/S3/Temporal is touched).
    from calibration import stack

    os.environ.setdefault("DATABASE_URL", stack.DATABASE_URL)
    os.environ.setdefault("DUCKLAKE_CATALOG_URL", stack.DUCKLAKE_CATALOG_URL)
    os.environ.setdefault("DUCKLAKE_DATA_PATH", stack.DUCKLAKE_DATA_PATH)
    os.environ.setdefault("DATARAUM_HOME", str(stack.WORKSPACE_DIR))
    os.environ.setdefault("DATARAUM_WORKSPACE_ID", stack.DATARAUM_WORKSPACE_ID)
    os.environ.setdefault("TEMPORAL_HOST", stack.TEMPORAL_HOST)
    os.environ.setdefault("TEMPORAL_NAMESPACE", stack.TEMPORAL_NAMESPACE)
    os.environ.setdefault("TEMPORAL_TASK_QUEUE", stack.TEMPORAL_TASK_QUEUE)
    os.environ.setdefault("S3_ENDPOINT", stack.S3_ENDPOINT)
    os.environ.setdefault("S3_BUCKET", stack.S3_BUCKET)
    os.environ.setdefault("S3_REGION", stack.S3_REGION)
    os.environ.setdefault("S3_USE_SSL", "false")
    os.environ.setdefault("S3_ACCESS_KEY_ID", stack.S3_ACCESS_KEY_ID)
    os.environ.setdefault("S3_SECRET_ACCESS_KEY", stack.S3_SECRET_ACCESS_KEY)

    from dataraum.analysis.hierarchies.judge import DimensionIdentityJudge
    from dataraum.llm import create_provider, load_llm_config

    # Construct like the phase does (config + provider, fail loud) — this is
    # the live-LLM leg, so a misconfiguration is a test failure, not a skip.
    config = load_llm_config()
    provider = create_provider(
        config.active_provider, config.providers[config.active_provider].model_dump()
    )
    return DimensionIdentityJudge(config=config, provider=provider)


def _routed_cells() -> list[tuple[dict[str, Any], str]]:
    import importlib

    # Dynamic import: the installed engine may predate the module (mypy runs
    # against vendored main; the importorskip at module top gates execution).
    routing = importlib.import_module("dataraum.analysis.hierarchies.routing")

    cells = json.loads(_FIXTURE.read_text())["cells"]
    out = []
    for c in cells:
        if c.get("c1_verdict") not in ("MERGE", "HIERARCHY") or "col_a" not in c:
            continue
        ev = {
            s: routing.ColumnEvidence(
                n_rows=c[f"col_{s}"]["n_rows"],
                n_distinct=c[f"col_{s}"]["n_distinct"],
                dtype=c[f"col_{s}"]["dtype"],
                sample_values=c[f"col_{s}"]["sample_distinct_values"],
            )
            for s in ("a", "b")
        }
        klass = (
            routing.route_alias(ev["a"], ev["b"])
            if c["c1_verdict"] == "MERGE"
            else routing.route_edge(ev["a"], ev["b"])
        )
        if klass is not None:
            out.append((c, klass))
    return out


@pytest.mark.llm
def test_veto_leg_through_engine_judge() -> None:
    """The names-only veto judge vetoes the routed (stack-wrong) structures."""
    judge = _judge()
    routed = _routed_cells()
    assert routed, "routing produced no veto targets — component 1 must be red too"

    verdicts: dict[str, str] = {}
    for cell, klass in routed:
        kind = "alias" if cell["c1_verdict"] == "MERGE" else "drilldown"
        result = judge.veto(
            table_name=cell["dataset"],
            all_columns=[cell["a"], cell["b"]],
            structures=[{
                "ref": cell["id"],
                "kind": kind,
                "members": [cell["a"], cell["b"]],
                "routed_class": klass,
            }],
        )
        assert result.success, f"{cell['id']}: judge call failed — {result.error}"
        (v,) = result.unwrap()
        verdicts[cell["id"]] = v.verdict
        print(f"[veto] {cell['id']} ({cell['klass']}, {klass}): {v.verdict} — {v.reason}")

    vetoed = sum(1 for v in verdicts.values() if v == "veto")
    print(f"\n[veto leg] {vetoed}/{len(verdicts)} routed structures vetoed")
    assert vetoed >= 7, (
        f"only {vetoed}/{len(verdicts)} routed structures vetoed (floor 7/9): "
        f"{verdicts} — the names-only judge is not delivering its measured "
        "performance through the engine prompts"
    )


@pytest.mark.llm
def test_conform_leg_no_false_merges() -> None:
    """The conform judge never CONFORMs a false-friend (L) pair; K reported."""
    judge = _judge()
    cells = json.loads(_FIXTURE.read_text())["cells"]
    targets = [c for c in cells if c["klass"] in ("K-disjoint-conform", "L-false-friend")]
    assert targets

    candidates = []
    for c in targets:
        candidates.append({
            "ref": c["id"],
            "left": {"fact_table": c["dataset"], "key": c["a"], "attributes": [],
                     "meanings": {}},
            "right": {"fact_table": c["dataset"], "key": c["b"], "attributes": [],
                      "meanings": {}},
        })
    result = judge.conform(candidates=candidates)
    assert result.success, f"conform call failed — {result.error}"

    by_ref = {v.pair_ref: v for v in result.unwrap()}
    for c in targets:
        v = by_ref.get(c["id"])
        print(f"[conform] {c['id']} ({c['klass']}, truth {c['truth']}): "
              f"{v.verdict if v else 'MISSING'} — {v.reason if v else ''}")

    false_merges = [
        c["id"] for c in targets
        if c["klass"] == "L-false-friend"
        and by_ref.get(c["id"]) is not None
        and by_ref[c["id"]].verdict == "conform"
    ]
    assert not false_merges, (
        f"false-friend pairs CONFORMed — the costly error (silent cross-fact "
        f"corruption): {false_merges}"
    )
