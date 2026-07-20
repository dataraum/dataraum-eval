"""Philipp: a dimension never has high cardinality. So cardinality is not a
screen bolted onto the FD question -- it IS the dimension question. Evaluating a
high-cardinality LHS as a dimension candidate is a category error.

Two consequences to test, free, no LLM:
 1. Are the RWD 'meaningful' FDs actually low-cardinality dimensions, or are many
    of them high-card FDs (title->booktitle) that are NOT dimensions?
 2. If we restrict to genuine dimension candidates (low abs-cardinality LHS,
    guarded by a min-row floor so small tables aren't over-filtered), what is
    left, and did the 'hard residual' vanish because it was never in scope?
"""
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import judge2, rwd  # noqa: E402

cands = rwd.exact_candidates()
n_real = sum(c["meaningful"] for c in cands)

def prof(t, col):
    df = rwd.load_table(t)
    one = judge2._blank_sentinels(df.select([col]), [col])
    return judge2._profile(one, col)

pc = {}
for c in cands:
    k = (c["table"], c["lhs"])
    if k not in pc:
        p = prof(*k)
        pc[k] = (p.distinct, p.non_null, p.distinct / max(p.non_null, 1))

def lhs(c): return pc[(c["table"], c["lhs"])]

# 1. absolute distinct count of the LHS, real vs junk
print("LHS ABSOLUTE distinct count — real dimensions vs junk\n")
def bucket(d):
    for hi, lab in [(10,"<=10"),(25,"<=25"),(50,"<=50"),(100,"<=100"),
                    (500,"<=500"),(5000,"<=5000"),(10**9,">5000")]:
        if d <= hi: return lab
order = ["<=10","<=25","<=50","<=100","<=500","<=5000",">5000"]
tab = defaultdict(lambda: [0,0])
for c in cands:
    d = lhs(c)[0]
    tab[bucket(d)][0 if c["meaningful"] else 1] += 1
print(f"  {'LHS distinct':10s} {'real':>6} {'junk':>6}")
cr = cj = 0
for b in order:
    r, j = tab[b]; cr += r; cj += j
    print(f"  {b:10s} {r:>6} {j:>6}   (cum real {cr}/{n_real}, junk {cj}/{len(cands)-n_real})")

# 2. dimension screen: keep if LHS abs-distinct <= D, but never filter tables
#    with < R rows (min-row guard). Sweep D.
print("\nDIMENSION SCREEN — keep LHS abs-distinct <= D  (min-row guard R=500:")
print("  a table with < R rows is too small to trust cardinality, so keep it)\n")
R = 500
for D in (25, 50, 100, 200, 500):
    surv = [c for c in cands
            if lhs(c)[0] <= D or lhs(c)[1] < R]
    sr = sum(x["meaningful"] for x in surv)
    junk_removed = (len(cands)-n_real) - (len(surv)-sr)
    print(f"  D={D:>4}: keep {len(surv):>3}  real {sr:>3}/{n_real} "
          f"(recall {sr/n_real:.3f})  junk-killed {junk_removed:>3}/{len(cands)-n_real} "
          f"({junk_removed/(len(cands)-n_real):.0%})  prec {sr/len(surv):.3f}")

# 3. did the column-LLM's 'destroyed real' concentrate on high-card LHS?
cache_p = Path(__file__).parent / "results_cols2.json"
if cache_p.exists():
    cache = json.loads(cache_p.read_text())
    cols = sorted({(c["table"], c["lhs"]) for c in cands})
    verdict = {}
    for t, col in cols:
        votes = [cache[f"{t}:{col}:{r}"]["groupable"] for r in range(3) if f"{t}:{col}:{r}" in cache]
        if votes: verdict[(t, col)] = sum(votes) >= 2
    # real pairs the column judge dropped (said not groupable)
    fn = [c for c in cands if c["meaningful"] and not verdict.get((c["table"], c["lhs"]), True)]
    print(f"\nColumn-LLM 'destroyed' {len(fn)} real pairs. Their LHS cardinality:")
    hi = sum(1 for c in fn if lhs(c)[0] > 100)
    print(f"  LHS abs-distinct > 100 (NOT a dimension): {hi}/{len(fn)}")
    print(f"  LHS abs-distinct <= 100 (a real dimension it wrongly dropped): {len(fn)-hi}/{len(fn)}")
    for c in sorted(fn, key=lambda c: -lhs(c)[0])[:12]:
        d, nn, kf = lhs(c)
        print(f"    {c['lhs'][:22]:22s} -> {c['rhs'][:20]:20s} distinct={d:>6} keyfrac={kf:.2f}")


def _extra():
    print("\n=== the genuine low-card dimension content of RWD ===")
    lowreal = [c for c in cands if c["meaningful"] and lhs(c)[0] <= 500]
    print(f"real pairs with LHS abs-distinct <= 500: {len(lowreal)}/{n_real}")
    for c in sorted(lowreal, key=lambda c: lhs(c)[0]):
        d, nn, kf = lhs(c)
        rp = prof(c["table"], c["rhs"])
        print(f"  {c['lhs'][:26]:26s} -> {c['rhs'][:22]:22s} "
              f"LHS distinct={d:>4} (of {nn:>6})  RHS distinct={rp.distinct}")
    print("\n=== and the low-card JUNK it must be told apart from ===")
    lowjunk = [c for c in cands if not c["meaningful"] and lhs(c)[0] <= 25]
    print(f"junk pairs with LHS abs-distinct <= 25: {len(lowjunk)}")
    from collections import Counter
    cnt = Counter((c["table"].split('.')[0][:24], c["lhs"]) for c in lowjunk)
    for (t, col), k in cnt.most_common(10):
        d = pc[(t + '.csv' if not t.endswith('.csv') else t, col)][0] if False else lhs(next(c for c in lowjunk if c['lhs']==col))[0]
        print(f"  {col[:24]:24s} {t:24s} {k:>2} junk pairs  (LHS distinct={d})")

_extra()
