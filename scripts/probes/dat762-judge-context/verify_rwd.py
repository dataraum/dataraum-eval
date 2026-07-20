"""Verify the RWD exact-slice counts myself before building a gate on them.

An agent reported: 390 exactly-holding candidates, 126 meaningful / 264 not.
An earlier agent reported "adult: 111 exact -> 2 meaningful". Those contradict.
This checks the raw CC-BY-4.0 files from Zenodo 8098909 and settles it.

ground_truth.csv      = positives only (table, lhs, rhs), no label column
included_candidates.csv = candidates with g3 >= 0.5 that were human-inspected
excluded_candidates.csv = the rest
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-philipp-Code-dataraum-dataraum-eval/"
    "8ccfc4a9-51ee-4df1-ae8f-f99d129146e0/scratchpad"
)


def load(name: str) -> list[dict[str, str]]:
    with (SCRATCH / name).open() as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    gt = load("ground_truth.csv")
    inc = load("included_candidates.csv")
    exc = load("excluded_candidates.csv")

    pos = {(r["table"], r["lhs"], r["rhs"]) for r in gt}
    print(f"ground_truth.csv rows={len(gt)} unique={len(pos)}")
    print(f"included_candidates.csv rows={len(inc)}")
    print(f"excluded_candidates.csv rows={len(exc)}")

    # every candidate, whether or not g3 is computable
    all_rows = inc + exc
    print(f"\ntotal ordered pairs = {len(all_rows)}")

    empty = [r for r in all_rows if r.get("empty", "").strip() == "True"]
    computable = [r for r in all_rows if r.get("empty", "").strip() != "True"]
    print(f"  empty (no computable g3) = {len(empty)}")
    print(f"  computable               = {len(computable)}")

    def g3(r: dict[str, str]) -> float:
        return float(r["g3"])

    exact = [r for r in computable if g3(r) == 1.0]
    approx = [r for r in computable if g3(r) < 1.0]
    print(f"    exact  (g3 == 1.0) = {len(exact)}")
    print(f"    approx (g3 <  1.0) = {len(approx)}")

    def key(r: dict[str, str]) -> tuple[str, str, str]:
        return (r["table"], r["lhs"], r["rhs"])

    exact_pos = [r for r in exact if key(r) in pos]
    exact_neg = [r for r in exact if key(r) not in pos]
    approx_pos = [r for r in approx if key(r) in pos]

    print("\n--- THE SLICE THE GATE WOULD USE ---")
    print(f"exactly-holding candidates = {len(exact)}")
    print(f"  meaningful (in ground truth) = {len(exact_pos)}")
    print(f"  NOT meaningful               = {len(exact_neg)}")
    if exact:
        print(f"  positive rate = {len(exact_pos) / len(exact):.1%}")
    print(f"\napproximate & meaningful (excluded from the gate) = {len(approx_pos)}")
    print(f"total design FDs = {len(exact_pos) + len(approx_pos)} (should equal {len(pos)})")

    # is the exact slice complete? the g3>=0.5 screen cannot skip g3==1.0
    exact_excluded = [r for r in exc if r.get("empty") != "True" and g3(r) == 1.0]
    print(f"\nexact candidates sitting in EXCLUDED file = {len(exact_excluded)} "
          f"(must be 0 for the slice to be complete)")

    print("\n--- per table (exact / meaningful / not) ---")
    tables = sorted({r["table"] for r in exact})
    tot_e = tot_m = 0
    for t in tables:
        e = [r for r in exact if r["table"] == t]
        m = [r for r in e if key(r) in pos]
        tot_e += len(e)
        tot_m += len(m)
        print(f"  {t:24s} {len(e):4d} / {len(m):3d} / {len(e) - len(m):3d}")
    print(f"  {'TOTAL':24s} {tot_e:4d} / {tot_m:3d} / {tot_e - tot_m:3d}")

    print("\n--- the contradicted claim: adult ---")
    adult = [r for r in all_rows if r["table"] == "adult.csv"]
    a_exact = [r for r in adult if r.get("empty") != "True" and g3(r) == 1.0]
    print(f"adult total ordered pairs = {len(adult)}")
    print(f"adult exactly-holding     = {len(a_exact)}  "
          f"(agent A said 111, agent B said 2)")
    print(f"adult meaningful          = {len([r for r in a_exact if key(r) in pos])}")
    print(f"adult g3 distribution     = "
          f"{Counter(round(g3(r), 1) for r in adult if r.get('empty') != 'True').most_common(5)}")


if __name__ == "__main__":
    main()
