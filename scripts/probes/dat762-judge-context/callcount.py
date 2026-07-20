"""How many LLM calls per dataset, given the engine's REAL screens?
Engine: NEAR_KEY_FRAC=0.9 (distinct>=0.9*rows -> excluded as determinant),
MIN_DISTINCT_DETERMINANT=3. LLM sees only pairs surviving both. 1 call/pair in prod.
"""
from __future__ import annotations
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import judge2, rwd  # noqa: E402

NEAR_KEY_FRAC = 0.9
MIN_DISTINCT_DETERMINANT = 3
MIN_ROWS_NEARKEY = 10  # Philipp's guard

cands = rwd.exact_candidates()
prof = {}
for c in cands:
    for col in (c["lhs"], c["rhs"]):
        k = (c["table"], col)
        if k not in prof:
            df = rwd.load_table(k[0])
            p = judge2._profile(judge2._blank_sentinels(df.select([col]), [col]), col)
            prof[k] = (p.distinct, p.non_null)

def is_determinant(t, col):
    d, n = prof[(t, col)]
    if d < MIN_DISTINCT_DETERMINANT:            # too coarse
        return False
    if n >= MIN_ROWS_NEARKEY and d >= NEAR_KEY_FRAC * n:  # near-key, guarded
        return False
    return True

per_table = defaultdict(lambda: [0, 0, 0])  # cand, llm-bound, real-of-llm
for c in cands:
    t = c["table"]
    per_table[t][0] += 1
    if is_determinant(t, c["lhs"]):
        per_table[t][1] += 1
        per_table[t][2] += c["meaningful"]

print("per table:  g3-candidates -> LLM-bound (LHS survives near-key%+min-row+min-distinct)")
tot = [0, 0, 0]
for t in sorted(per_table):
    cd, llm, real = per_table[t]
    cols = len({c['lhs'] for c in cands if c['table']==t} | {c['rhs'] for c in cands if c['table']==t})
    for i in range(3): tot[i] += per_table[t][i]
    print(f"  {t.split('.')[0][:34]:34s} ~{cols:>2} cols  {cd:>3} cand -> {llm:>3} LLM  ({real} real)")
print(f"  {'TOTAL (9 tables = one dataset)':34s}         {tot[0]:>3} cand -> {tot[1]:>3} LLM  ({tot[2]} real)")
print(f"\nLLM calls for the whole RWD dataset: {tot[1]}  (1 rep, production)")
print(f"  vs judging every g3 candidate: {tot[0]}   -> filter removes {tot[0]-tot[1]} ({(tot[0]-tot[1])/tot[0]:.0%})")
