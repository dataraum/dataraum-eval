"""The operating point, stated straight. keyfrac = distinct/rows (a PERCENTAGE),
min-row guard so small tables aren't screened. Then the fed judge V. Uses
already-paid results_rwd.json — no new calls.
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
cache = json.loads((Path(__file__).parent / "results_rwd.json").read_text())

kf = {}
for c in cands:
    k = (c["table"], c["lhs"])
    if k not in kf:
        df = rwd.load_table(k[0])
        p = judge2._profile(judge2._blank_sentinels(df.select([k[1]]), [k[1]]), k[1])
        kf[k] = (p.distinct / max(p.non_null, 1), p.non_null)

def v_majority(c):
    votes = [cache[f"{c['table']}:{c['lhs']}:{c['rhs']}:V:{r}"]["meaningful"]
             for r in range(3) if f"{c['table']}:{c['lhs']}:{c['rhs']}:V:{r}" in cache]
    return (sum(votes) >= 2) if votes else True

def calib(kept):
    conf = defaultdict(lambda: [0, 0])
    for c in kept:
        for r in range(3):
            key = f"{c['table']}:{c['lhs']}:{c['rhs']}:V:{r}"
            if key in cache:
                v = cache[key]
                conf[v["confidence"]][0] += (v["meaningful"] == c["meaningful"])
                conf[v["confidence"]][1] += 1
    return {c: (conf[c][0], conf[c][1]) for c in ("high","medium","low")}

def line(name, kept):
    sr = sum(x["meaningful"] for x in kept)
    prec = sr/len(kept) if kept else 0
    ca = calib(kept)
    cs = "  ".join(f"{c}={ca[c][0]}/{ca[c][1]}={ca[c][0]/ca[c][1]:.2f}"
                   for c in ("high","medium","low") if ca[c][1])
    print(f"{name}")
    print(f"   keep {len(kept):>3}   precision {prec:.3f}   recall {sr/n_real:.3f}   real {sr}/{n_real}")
    print(f"   calibration: {cs}")

print(f"390 exact FDs, base rate {n_real/len(cands):.3f} (this is the 'ship-all' precision)\n")
line("mechanical stack alone = ship everything:", cands)
print()
line("judge V alone (no screen):", [c for c in cands if v_majority(c)])
print()
# percentage screen with min-row guard, then V
T, R = 0.9, 500
surv = [c for c in cands if kf[(c["table"], c["lhs"])][0] < T or kf[(c["table"], c["lhs"])][1] < R]
line(f"near-key%% screen (drop distinct/rows >= {T}, skip tables < {R} rows) -> judge V:",
     [c for c in surv if v_majority(c)])
