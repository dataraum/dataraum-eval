"""How few questions resolve the most candidates?

The finder is fine: g3 gets ~all of them. The problem is what happens next.
Pairs are combinatorial; columns are not. If a column is not something anyone
groups by, EVERY pair with it on the left dies in one answer.

Measures the leverage of asking about a COLUMN instead of a PAIR.
"""
from __future__ import annotations
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import rwd  # noqa: E402

def main() -> None:
    cands = rwd.exact_candidates()
    by_table = defaultdict(list)
    for c in cands:
        by_table[c["table"]].append(c)

    print(f"{len(cands)} candidate pairs over {len(by_table)} tables\n")

    tot_lhs = tot_pairs = pure_lhs = pure_pairs = 0
    print(f"{'table':38s} {'pairs':>5} {'LHS cols':>8} {'pure':>5} {'ratio':>6}")
    for t, rows in sorted(by_table.items()):
        groups = defaultdict(list)
        for c in rows:
            groups[c["lhs"]].append(c["meaningful"])
        pure = [k for k, v in groups.items() if len(set(v)) == 1]
        pp = sum(len(groups[k]) for k in pure)
        tot_lhs += len(groups); tot_pairs += len(rows)
        pure_lhs += len(pure); pure_pairs += pp
        print(f"{t.split('.')[0][:38]:38s} {len(rows):>5} {len(groups):>8} "
              f"{len(pure):>5} {len(rows)/len(groups):>6.1f}")
    print(f"\n{'TOTAL':38s} {tot_pairs:>5} {tot_lhs:>8} {pure_lhs:>5} "
          f"{tot_pairs/tot_lhs:>6.1f}")

    print(f"\nLHS columns whose pairs all share one label: {pure_lhs}/{tot_lhs} "
          f"({pure_lhs/tot_lhs:.1%})")
    print(f"  ...those cover {pure_pairs}/{tot_pairs} pairs ({pure_pairs/tot_pairs:.1%})")
    print(f"\nASK-PER-COLUMN vs ASK-PER-PAIR: {tot_lhs} questions vs {tot_pairs} "
          f"= {tot_pairs/tot_lhs:.1f}x fewer")

    # Where does the junk mass actually sit?
    junk = defaultdict(int)
    for c in cands:
        if not c["meaningful"]:
            junk[(c["table"], c["lhs"])] += 1
    ranked = sorted(junk.items(), key=lambda kv: -kv[1])
    total_junk = sum(junk.values())
    print(f"\n--- {total_junk} junk pairs sit on {len(junk)} (table, LHS) columns ---")
    run = 0
    for i, ((t, col), n) in enumerate(ranked[:15], 1):
        run += n
        print(f"  {i:>2}. {col[:26]:26s} {t.split('.')[0][:22]:22s} "
              f"{n:>3} junk  (cumulative {run}/{total_junk} = {run/total_junk:.0%})")
    for k in (5, 10, 20, 30):
        got = sum(n for _, n in ranked[:k])
        print(f"  top {k:>2} columns kill {got:>3}/{total_junk} junk pairs ({got/total_junk:.0%})")


if __name__ == "__main__":
    main()
