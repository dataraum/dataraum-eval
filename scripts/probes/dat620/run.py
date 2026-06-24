"""DAT-620 lane-1 runner — the A-vs-B kill gate.

    uv run python scripts/probes/dat620/run.py --dry-run     # no LLM: show fixture+prompts
    uv run python scripts/probes/dat620/run.py               # real run (needs ANTHROPIC_API_KEY)

Builds a long-format finance fixture over disjoint holdout seeds, runs both legs (A=feed
-only, B=value-level semantic) on the SAME inputs, scores per-value precision/recall +
trap correctness + reconstructed gross-margin error, and reports the B−A separation.

Verdict map:
  A already high (acc≈1, unmapped/exclude traps clean, gp_err≈0) and B no better
      → no labeler to build; the fix is DAT-616 (feed top_values+ontology). CUT proposer.
  A fails the traps / undercounts gross profit but B fixes it
      → value-level labeling is load-bearing → BUILD tier B (extend semantic agent).
  Neither clears the traps
      → human teach/confirmation required → BUILD tier C (binding table + teach).
"""

from __future__ import annotations

import argparse
import os
import sys

from generate import make_fixture
from labeler import (
    _build_request,
    label,
    load_finance_concepts,
    make_provider,
)
from score import LegScore, Pooled, pool, score

_HOLDOUT = range(5_000, 5_006)  # disjoint from any future fit range; pooled


def _dry_run(seed: int, hard: bool) -> None:
    concepts = load_finance_concepts()
    fixture = make_fixture(seed, hard=hard)
    print(f"=== fixture (seed {seed}) — top_values(account_type) ===")
    for v, n in fixture.top_values():
        concept, klass = fixture.oracle[v]
        print(f"  {n:5d}  {v:28s} -> {concept:22s} [{klass}]")
    print(f"\n  gross_profit (oracle) = {fixture.gross_profit:,.2f}")
    print(f"  revenue_total (oracle) = {fixture.revenue_total:,.2f}")
    for leg in ("A", "B"):
        req = _build_request(leg, fixture.top_values(), concepts, None)
        print(f"\n=== leg {leg} system ===\n{req.system}")
        print(f"\n=== leg {leg} user ===\n{req.messages[0].content}")


def _report(pooled: dict[str, Pooled], n_seeds: int) -> None:
    print(f"\n=== DAT-620 lane-1 verdict ({n_seeds} holdout seeds pooled) ===\n")
    hdr = f"{'metric':24s} {'leg A':>10s} {'leg B':>10s} {'B - A':>10s}"
    print(hdr)
    print("-" * len(hdr))

    def row(name: str, a: float, b: float) -> None:
        print(f"{name:24s} {a:10.3f} {b:10.3f} {b - a:+10.3f}")

    A, B = pooled["A"], pooled["B"]
    row("value accuracy", A.accuracy, B.accuracy)
    row("macro precision", A.macro_precision, B.macro_precision)
    row("macro recall", A.macro_recall, B.macro_recall)
    row("gross_profit rel.err", A.gp_rel_error, B.gp_rel_error)
    print("\nper-class accuracy (the traps):")
    for k in sorted(set(A.class_accuracy) | set(B.class_accuracy)):
        row(f"  {k}", A.class_accuracy.get(k, 0.0), B.class_accuracy.get(k, 0.0))

    print("\nfailure mode per class — correct / abstain(safe) / mislabel(dangerous):")
    for k in sorted(set(A.class_breakdown) | set(B.class_breakdown)):
        a = A.class_breakdown.get(k, (0.0, 0.0, 0.0))
        b = B.class_breakdown.get(k, (0.0, 0.0, 0.0))
        print(
            f"  {k:20s} A {a[0]:.2f}/{a[1]:.2f}/{a[2]:.2f}   "
            f"B {b[0]:.2f}/{b[1]:.2f}/{b[2]:.2f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no LLM; print fixture+prompts")
    ap.add_argument("--hard", action="store_true", help="HARD universe (codes/abbrev/ambiguity)")
    ap.add_argument("--model", default=None, help="override model id (default sonnet-4-6)")
    ap.add_argument("--seeds", type=int, default=len(_HOLDOUT), help="how many holdout seeds")
    args = ap.parse_args()

    seeds = list(_HOLDOUT)[: args.seeds]

    if args.dry_run:
        _dry_run(seeds[0], args.hard)
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — needed for the real run.", file=sys.stderr)
        return 2

    concepts = load_finance_concepts()
    provider = make_provider()
    scores: dict[str, list[LegScore]] = {"A": [], "B": []}
    for seed in seeds:
        fixture = make_fixture(seed, hard=args.hard)
        tv = fixture.top_values()
        for leg in ("A", "B"):
            preds = label(provider, leg, tv, concepts, model=args.model)
            scores[leg].append(score(fixture, preds))
            print(f"  seed {seed} leg {leg}: scored {len(preds)} values", file=sys.stderr)

    pooled = {leg: pool(leg, scores[leg]) for leg in ("A", "B")}
    _report(pooled, len(seeds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
