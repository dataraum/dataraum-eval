"""Where do real dimensions sit on keyfrac vs the junk keys? The engine's 0.9 is
'not quite a key'. A dimension is LOW cardinality. Sweep the threshold: LLM calls
(survivors) vs recall of real dimensions. If real dims are all very low keyfrac,
a stricter cut slashes calls at zero recall cost.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import judge2, rwd  # noqa: E402

cands = rwd.exact_candidates()
n_real = sum(c["meaningful"] for c in cands)
prof = {}
for c in cands:
    k = (c["table"], c["lhs"])
    if k not in prof:
        df = rwd.load_table(k[0])
        p = judge2._profile(judge2._blank_sentinels(df.select([k[1]]), [k[1]]), k[1])
        prof[k] = p.distinct / max(p.non_null, 1)

print("keyfrac (distinct/rows) of the LHS — real dimensions vs junk\n")
reals = sorted(prof[(c["table"], c["lhs"])] for c in cands if c["meaningful"])
junks = sorted(prof[(c["table"], c["lhs"])] for c in cands if not c["meaningful"])
def q(v, p): return v[int(p*(len(v)-1))]
print(f"  REAL dims LHS keyfrac: min={reals[0]:.3f} p50={q(reals,.5):.3f} "
      f"p90={q(reals,.9):.3f} max={reals[-1]:.3f}")
print(f"  JUNK     LHS keyfrac: min={junks[0]:.3f} p50={q(junks,.5):.3f} "
      f"p90={q(junks,.9):.3f} max={junks[-1]:.3f}")

print("\nthreshold sweep — drop LHS keyfrac >= T (min-row guard n>=10):")
print(f"  {'T':>5} {'LLM calls':>9} {'real kept':>10} {'recall':>7}")
for T in (0.9, 0.7, 0.5, 0.3, 0.2, 0.1, 0.05):
    surv = [c for c in cands if prof[(c["table"], c["lhs"])] < T]
    real = sum(x["meaningful"] for x in surv)
    print(f"  {T:>5.2f} {len(surv):>9} {real:>10}/{n_real} {real/n_real:>7.3f}")
print("\n(LLM calls = survivors the judge must see; real kept = recall ceiling)")
