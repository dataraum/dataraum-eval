"""Does every prompt's premise actually hold? Reads no labels.

Every prompt asserts "A -> B holds exactly". If that is false for the rows we
render, we are asking the judge to explain something that isn't there. The
frame agent found 24 pairs where it fails, root-caused to the literal 'NULL'
sentinel. This checks the fix over all 390 and prints what still breaks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import polars as pl  # noqa: E402

import judge2  # noqa: E402
import rwd  # noqa: E402


def holds_raw(table: str, a: str, b: str) -> bool:
    """Premise WITHOUT the sentinel fix — the state the agent found."""
    df = rwd.load_table(table)
    pair = df.select([a, b]).drop_nulls()
    if not len(pair):
        return False
    return pair.n_unique(subset=[a]) == pair.n_unique(subset=[a, b])


def main() -> None:
    cands = rwd.exact_candidates()
    broken_raw, broken_fixed = [], []
    for c in cands:
        t, a, b = c["table"], c["lhs"], c["rhs"]
        if not holds_raw(t, a, b):
            broken_raw.append((t, a, b))
        if not judge2.holds_exactly(t, a, b):
            broken_fixed.append((t, a, b))

    print(f"candidates: {len(cands)}")
    print(f"premise FALSE without the 'NULL' sentinel fix: {len(broken_raw)}")
    print(f"premise FALSE with    the 'NULL' sentinel fix: {len(broken_fixed)}")

    if broken_fixed:
        print("\nSTILL BROKEN — do not run until these are understood:")
        for t, a, b in broken_fixed:
            f = judge2.facts(t, a, b)
            print(f"  {t.split('.')[0][:26]:26s} {a[:22]:22s} -> {b[:22]:22s} "
                  f"n={f.n_rows:>7,} dA={f.a.distinct:>6,} dB={f.b.distinct:>6,}")
    else:
        print("\nall 390 premises hold with the fix.")

    # how much did the sentinel distort what the judge is SHOWN?
    print("\n--- sentinel's reach beyond the 24 broken pairs ---")
    hit = 0
    for c in cands:
        df = rwd.load_table(c["table"])
        cols = [c["lhs"], c["rhs"]]
        n = (
            df.select(
                [pl.col(x).is_in(list(judge2.NULL_TOKENS)).sum().alias(x) for x in cols]
            )
            .sum_horizontal()
            .item()
        )
        if n:
            hit += 1
    print(f"candidates where a rendered column contains the sentinel: {hit}/{len(cands)}")

    print("\n--- support, with the fix applied ---")
    ns = sorted(judge2.facts(c["table"], c["lhs"], c["rhs"]).n_rows for c in cands)
    print(f"  min={ns[0]:,}  p25={ns[len(ns) // 4]:,}  median={ns[len(ns) // 2]:,}  max={ns[-1]:,}")
    for thr in (2, 10, 100, 1000):
        k = sum(1 for n in ns if n <= thr)
        print(f"  n_rows <= {thr:>5,}: {k:>3}/{len(ns)} ({k / len(ns):.1%})")


if __name__ == "__main__":
    main()
