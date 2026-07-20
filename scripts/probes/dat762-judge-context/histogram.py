"""DAT-762 identity-confidence calibration — CACHE-ONLY, zero LLM calls, GROUNDED.

Grades the batched float-confidence judge (results_batch.json) against the held-out
ground truth (rwd.exact_candidates(): `meaningful` True iff annotated a real
dimension relationship). Confidence is decisiveness-of-verdict, so `correct` =
(judge.meaningful == truth.meaningful). This is what pins IDENTITY_MERGE_MIN:
does confidence separate correct from incorrect, and — the only thing that matters
for a MERGE — does any TRUTH-coincidental pair get a confident meaningful verdict?

    uv run python scripts/probes/dat762-judge-context/histogram.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import rwd  # noqa: E402  (local: table loads + truth map, no LLM)

CACHE = HERE / "results_batch.json"
MERGE_MIN = 0.85


def main() -> None:
    cache = json.loads(CACHE.read_text())
    verd: dict[tuple[str, str, str], dict] = {}
    for ck, rec in cache.items():
        table = ck.split("#")[0]
        for pair, v in rec.items():
            lhs, rhs = pair.split("->")
            verd[(table, lhs, rhs)] = v
    truth = {(c["table"], c["lhs"], c["rhs"]): c["meaningful"] for c in rwd.exact_candidates()}

    rows = [(verd[k]["confidence"], verd[k]["meaningful"], truth[k])
            for k in verd if k in truth]
    print(f"\n{len(rows)} graded pairs (cache ∩ truth) | ZERO LLM calls\n")

    # ---- calibration: P(correct) by confidence band; correct = verdict==truth -----
    print("CALIBRATION — P(judge correct | confidence band):")
    band = defaultdict(lambda: [0, 0])
    for conf, mean, tru in rows:
        b = "decisive ≥0.85" if conf >= 0.85 else "probable 0.5-0.85" if conf >= 0.5 else "guessing <0.5"
        band[b][0] += (mean == tru)
        band[b][1] += 1
    for b in ("decisive ≥0.85", "probable 0.5-0.85", "guessing <0.5"):
        ok, n = band[b]
        print(f"  {b:20} {ok:3}/{n:3} correct = {ok / n:.2f}" if n else f"  {b:20}  (none)")
    hi = band["decisive ≥0.85"]
    lo = band["guessing <0.5"]
    g1 = hi[0] / hi[1] - (lo[0] / lo[1] if lo[1] else 0)
    print(f"\n  G1 lift  P(correct|decisive) − P(correct|guessing) = {g1:+.2f}  (gate ≥0.25)")
    print(f"  G2       P(correct|decisive)                        = {hi[0] / hi[1]:.2f}  (gate ≥0.80)")

    # ---- THE merge-safety question --------------------------------------------
    # Engine merges iff verdict=meaningful AND conf≥MERGE_MIN. A merge is CORRUPTION
    # only when the pair is truth-coincidental. Count them, and show the confidence
    # the judge gave truth-coincidental pairs it (wrongly) called meaningful.
    merges = [(c, m, t) for c, m, t in rows if m and c >= MERGE_MIN]
    bad_merges = [(c, m, t) for c, m, t in merges if not t]
    print(f"\nAT IDENTITY_MERGE_MIN = {MERGE_MIN} (merge iff meaningful ∧ conf≥min):")
    print(f"  merges fired            : {len(merges)}")
    print(f"  CORRUPT merges (truth=coincidental, merged): {len(bad_merges)}")

    # ---- restrict to the IDENTITY lane's population: equal-cardinality bijections.
    # The engine routes to the identity judge ONLY pairs where distinct(lhs)==distinct(rhs)
    # (a relabeling bijection). dim→attr FDs (distinct(lhs) > distinct(rhs)) are a
    # different lane and never reach this judge. Recompute the merge-FP risk there.
    card: dict[tuple[str, str], int] = {}

    def distinct(table: str, col: str) -> int:
        key = (table, col)
        if key not in card:
            df = rwd.load_table(table)
            card[key] = df.select(col).unique().height
        return card[key]

    bij_rows = []
    for k in verd:
        if k not in truth:
            continue
        _, lhs, rhs = k
        table = k[0]
        if distinct(table, lhs) == distinct(table, rhs):
            bij_rows.append((verd[k]["confidence"], verd[k]["meaningful"], truth[k]))

    bij_fp = sorted((c for c, m, t in bij_rows if m and not t), reverse=True)
    all_fp = sorted((c for c, m, t in rows if m and not t), reverse=True)
    print(f"\n  Merge-FP class (judge=meaningful but truth=coincidental):")
    print(f"    ALL exact-FD pairs      : {len(all_fp)}  | ≥{MERGE_MIN}: {sum(c >= MERGE_MIN for c in all_fp)}  {[round(c, 2) for c in all_fp if c >= MERGE_MIN]}")
    print(f"    EQUAL-CARD bijections   : {len(bij_fp)}  | ≥{MERGE_MIN}: {sum(c >= MERGE_MIN for c in bij_fp)}  {[round(c, 2) for c in bij_fp if c >= MERGE_MIN]}   <- the identity lane's actual FP risk")
    print(f"\n  Bijection subset size: {len(bij_rows)}/{len(rows)} pairs are equal-cardinality (identity-lane population).")
    if bij_fp:
        print(f"    lowest threshold that blocks every bijection FP merge: {max(bij_fp) + 0.01:.2f}")
    else:
        print(f"    NO equal-cardinality bijection is a confident false-merge — the identity lane is clean at {MERGE_MIN}.")

    # ---- the identity lane's actual separation: every equal-card bijection ------
    true_alias = sorted((c for c, m, t in bij_rows if t), reverse=True)
    coincid = sorted((c for c, m, t in bij_rows if not t), reverse=True)
    print(f"\n  IDENTITY-LANE SEPARATION ({len(bij_rows)} equal-card bijections):")
    print(f"    TRUE aliases  (should merge, n={len(true_alias)}): conf {[round(c, 2) for c in true_alias]}")
    print(f"    COINCIDENTAL  (must not,    n={len(coincid)}): conf {[round(c, 2) for c in coincid]}")
    if true_alias and coincid:
        print(f"\n    dead zone = ( worst coincidental {max(coincid):.2f} , weakest true alias "
              f"{min(true_alias):.2f} ) → center {(max(coincid) + min(true_alias)) / 2:.2f}")


if __name__ == "__main__":
    main()
