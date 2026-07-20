"""Post-hoc diagnostics for the two anomalies the gate exposed. Changes nothing.

1. Why is `medium` anti-predictive? It breaks monotonicity in every cut, which
   contradicts the gate's own assumption that medium sits between high and low.
2. What is `low` actually tracking — error probability, or support thinness?
   G1 assumes the former. If it is the latter, G1 cannot pass by construction.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import grade_rwd  # noqa: E402
import judge2  # noqa: E402
import rwd  # noqa: E402

THIN = 1000


def main() -> None:
    res = grade_rwd.load_results()
    cands = rwd.exact_candidates()
    truth = {(c["table"], c["lhs"], c["rhs"]): c["meaningful"] for c in cands}
    n_rows = {
        (c["table"], c["lhs"], c["rhs"]): judge2.facts(c["table"], c["lhs"], c["rhs"]).n_rows
        for c in cands
    }

    calls = []
    for r in res.values():
        if "error" in r:
            continue
        k = (r["table"], r["lhs"], r["rhs"])
        calls.append({**r, "pred": r["meaningful"], "truth": truth[k], "n_rows": n_rows[k]})

    print("=" * 78)
    print("1. COMPOSITION OF EACH CONFIDENCE BUCKET — what is the judge saying?")
    print("=" * 78)
    print("   base rate of `meaningful` in the slice: 32.3%\n")
    for arm in ("V", "VH"):
        print(f"  arm {arm}")
        for conf in ("high", "medium", "low"):
            sub = [r for r in calls if r["arm"] == arm and r["confidence"] == conf]
            if not sub:
                print(f"    {conf:<6}: (none)")
                continue
            says_yes = sum(1 for r in sub if r["pred"])
            truly_yes = sum(1 for r in sub if r["truth"])
            ok = sum(1 for r in sub if r["pred"] == r["truth"])
            # Of the errors in this bucket, which direction?
            fp = sum(1 for r in sub if r["pred"] and not r["truth"])
            fn = sum(1 for r in sub if not r["pred"] and r["truth"])
            print(
                f"    {conf:<6}: n={len(sub):>4}  says-meaningful={says_yes / len(sub):5.1%}  "
                f"truly-meaningful={truly_yes / len(sub):5.1%}  "
                f"correct={ok / len(sub):5.1%}  [FP={fp} FN={fn}]"
            )
        print()

    print("=" * 78)
    print("2. WHAT DOES `low` TRACK — error, or thin support?")
    print("=" * 78)
    for arm in ("V", "VH"):
        low = [r for r in calls if r["arm"] == arm and r["confidence"] == "low"]
        thin_low = sum(1 for r in low if r["n_rows"] < THIN)
        print(f"  arm {arm}: {len(low)} low calls, {thin_low} on thin support "
              f"({thin_low / len(low):.1%} if any)" if low else f"  arm {arm}: no low calls")
    print()
    for arm in ("V", "VH"):
        for stratum, keep in (("thin ", lambda r: r["n_rows"] < THIN),
                              ("thick", lambda r: r["n_rows"] >= THIN)):
            sub = [r for r in calls if r["arm"] == arm and keep(r)]
            cc = Counter(r["confidence"] for r in sub)
            n = len(sub)
            print(f"  {arm:<3} {stratum}: high={cc['high'] / n:5.1%} medium={cc['medium'] / n:5.1%} "
                  f"low={cc['low'] / n:5.1%}   (n={n})")
    print("\n  If `low` fires on thin support rather than on error, G1 cannot pass:")
    print("  a low-confidence call on a thin pair is usually still CORRECT (the thin")
    print("  stratum is 86.8% not-meaningful, and 'not meaningful' is the right answer).")

    print("\n" + "=" * 78)
    print("3. THE DEGENERATE-SHORTCUT CHECK — is accuracy just 'always say no'?")
    print("=" * 78)
    print("   always-no on the whole slice scores 67.7% accuracy.")
    for arm in ("V", "VH"):
        sub = [r for r in calls if r["arm"] == arm]
        acc = sum(1 for r in sub if r["pred"] == r["truth"]) / len(sub)
        says_yes = sum(1 for r in sub if r["pred"]) / len(sub)
        print(f"  {arm:<3} accuracy={acc:.3f}  says-meaningful={says_yes:.1%} "
              f"(truth: 32.3%)")


if __name__ == "__main__":
    main()
