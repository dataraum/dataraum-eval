"""The one architecture the negative results leave standing:
free cardinality screen -> pair judge V on the survivors.

Does pre-screening the keys change what V has to do? Uses the ALREADY-PAID
results_rwd.json (V arm), no new calls.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import judge2, rwd  # noqa: E402

cands = rwd.exact_candidates()
n_real = sum(c["meaningful"] for c in cands)
n_junk = len(cands) - n_real

cache = json.loads((Path(__file__).parent / "results_rwd.json").read_text())

def prof(t, col):
    df = rwd.load_table(t)
    one = judge2._blank_sentinels(df.select([col]), [col])
    return judge2._profile(one, col)

keyfrac = {}
for c in cands:
    k = (c["table"], c["lhs"])
    if k not in keyfrac:
        p = prof(*k); keyfrac[k] = p.distinct / max(p.non_null, 1)

def v_says_meaningful(c):
    votes = []
    for r in range(3):
        for key in (f"{c['table']}:{c['lhs']}:{c['rhs']}:V:{r}",):
            if key in cache: votes.append(cache[key]["meaningful"])
    return (sum(votes) >= 2) if votes else True

def v_conf_correct(c):
    """return list of (confidence, correct) for V's 3 reps"""
    out = []
    for r in range(3):
        key = f"{c['table']}:{c['lhs']}:{c['rhs']}:V:{r}"
        if key in cache:
            v = cache[key]
            out.append((v["confidence"], v["meaningful"] == c["meaningful"]))
    return out

def report(surv, name):
    kept = [c for c in surv if v_says_meaningful(c)]
    sr = sum(x["meaningful"] for x in kept)
    prec = sr / len(kept) if kept else 0
    print(f"  {name:38s} final keep {len(kept):>3}  real {sr:>3}/{n_real} "
          f"(recall {sr/n_real:.3f})  prec {prec:.3f}")
    # calibration on the FINAL kept set (what actually reaches the user)
    from collections import defaultdict
    conf = defaultdict(lambda: [0, 0])
    for c in kept:
        for cf, ok in v_conf_correct(c):
            conf[cf][0] += ok; conf[cf][1] += 1
    cal = "  ".join(f"{c}:{conf[c][0]}/{conf[c][1]}" for c in ("high","medium","low") if conf[c][1])
    print(f"    {'':38s} calibration {cal}")

print(f"390 pairs, {n_real} real / {n_junk} junk (base {n_real/len(cands):.3f})\n")
print("A) V pair judge alone (already measured, for reference):")
report(cands, "V on all 390")
print("\nB) cardinality screen THEN V on survivors:")
for thr in (0.99, 0.95, 0.9):
    surv = [c for c in cands if keyfrac[(c["table"], c["lhs"])] < thr]
    dropped_junk = sum(1 for c in cands if keyfrac[(c["table"],c["lhs"])]>=thr and not c["meaningful"])
    dropped_real = sum(1 for c in cands if keyfrac[(c["table"],c["lhs"])]>=thr and c["meaningful"])
    print(f"  [screen keyfrac<{thr}: drops {dropped_junk} junk, {dropped_real} real before V]")
    report(surv, f"screen<{thr} -> V")
