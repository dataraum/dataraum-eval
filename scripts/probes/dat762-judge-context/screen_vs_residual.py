"""Test the UX agent's central reconciliation: is the junk CARDINALITY-separable
(free, no LLM) or is it the LLM-hard RESIDUAL?

The agent claims column cardinality kills ~2/3 of the junk for free. But my
leverage probe's top-2 junk producers (p1series/p2series, 44 pairs) are low-card
columns, not keys. So measure the pure structural screen directly and see how
much it actually removes, at what recall cost, against the LLM column judge.
"""
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import judge2, rwd  # noqa: E402

cands = rwd.exact_candidates()
n_real = sum(c["meaningful"] for c in cands)
n_junk = len(cands) - n_real

def prof(t, col):
    df = rwd.load_table(t)
    one = judge2._blank_sentinels(df.select([col]), [col])
    return judge2._profile(one, col)

# cache column profiles
keyfrac = {}
for c in cands:
    k = (c["table"], c["lhs"])
    if k not in keyfrac:
        p = prof(*k)
        keyfrac[k] = p.distinct / max(p.non_null, 1)

def grade(surv, name):
    sr = sum(x["meaningful"] for x in surv)
    junk_removed = n_junk - (len(surv) - sr)
    prec = sr / len(surv) if surv else 0
    print(f"  {name:44s} keep {len(surv):>3}  real {sr:>3}/{n_real} "
          f"(recall {sr/n_real:.3f})  junk-killed {junk_removed:>3}/{n_junk} "
          f"({junk_removed/n_junk:.0%})  prec {prec:.3f}")

print(f"390 pairs, {n_real} real / {n_junk} junk (base {n_real/len(cands):.3f})\n")
print("PURE CARDINALITY SCREEN — drop pairs whose LHS is near-unique (a key):")
for thr in (0.99, 0.95, 0.9, 0.8):
    surv = [c for c in cands if keyfrac[(c["table"], c["lhs"])] < thr]
    grade(surv, f"drop LHS keyfrac >= {thr}")

# what does the screen MISS — junk on low-card LHS (the residual)
resid_junk = [c for c in cands if not c["meaningful"] and keyfrac[(c["table"], c["lhs"])] < 0.9]
print(f"\nJunk the 0.9 screen CANNOT remove (low-card LHS): {len(resid_junk)}/{n_junk}")
by_lhs = defaultdict(int)
for c in resid_junk:
    by_lhs[(c["table"], c["lhs"])] += 1
for (t, col), k in sorted(by_lhs.items(), key=lambda x: -x[1])[:10]:
    kf = keyfrac[(t, col)]
    print(f"    {col[:24]:24s} {t.split('.')[0][:20]:20s} {k:>2} junk  keyfrac={kf:.3f}")

# now the LLM column judge, if the run finished
cache_p = Path(__file__).parent / "results_cols2.json"
if cache_p.exists():
    cache = json.loads(cache_p.read_text())
    cols = sorted({(c["table"], c["lhs"]) for c in cands})
    have = all(f"{t}:{col}:{r}" in cache for t, col in cols for r in range(3))
    print(f"\nLLM COLUMN JUDGE ('do you group by this?'): "
          f"{'complete' if have else 'INCOMPLETE — partial'}")
    verdict = {}
    for t, col in cols:
        votes = [cache[f"{t}:{col}:{r}"] for r in range(3) if f"{t}:{col}:{r}" in cache]
        if votes:
            verdict[(t, col)] = sum(v["groupable"] for v in votes) >= 2
    surv = [c for c in cands if verdict.get((c["table"], c["lhs"]), True)]
    grade(surv, "LLM says groupable (majority of 3)")
    # confidence calibration on the column question
    conf = defaultdict(lambda: [0, 0])
    truth_col = {}
    for c in cands:
        truth_col.setdefault((c["table"], c["lhs"]), False)
        if c["meaningful"]:
            truth_col[(c["table"], c["lhs"])] = True
    for t, col in cols:
        for r in range(3):
            k = f"{t}:{col}:{r}"
            if k not in cache: continue
            v = cache[k]
            correct = (v["groupable"] == truth_col[(t, col)])
            conf[v["confidence"]][0] += correct
            conf[v["confidence"]][1] += 1
    print("  column-question calibration:")
    for c in ("high", "medium", "low"):
        ok, tot = conf[c]
        if tot: print(f"    {c:6s} {ok}/{tot} = {ok/tot:.3f}")
