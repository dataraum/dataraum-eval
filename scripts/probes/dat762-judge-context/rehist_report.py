"""DAT-762 re-histogram report — CACHE-ONLY, zero LLM calls.

Reads results_rehist.json (the REDESIGNED directional identity judge over held-out
bijections + a constructed neutral panel) and reports the separation, the merge
outcome at REL_CONFIRM_MIN=0.7, and the distribution shape.
"""

from __future__ import annotations

import json
from pathlib import Path

CACHE = Path(__file__).parent / "results_rehist.json"
FLOOR = 0.7


def main() -> None:
    recs = list(json.loads(CACHE.read_text()).values())
    real = [r for r in recs if r["table"] != "constructed"]
    cons = [r for r in recs if r["table"] == "constructed"]

    def show(label: str, rows: list[dict]) -> None:
        print(f"\n{label}")
        for r in sorted(rows, key=lambda x: -x["confidence"]):
            tag = "alias " if r["truth"] else "COINC "
            gate = "MERGE " if r["confidence"] >= FLOOR else "surface"
            print(f"  {r['confidence']:.2f} {gate} [{tag}] {r['a']} == {r['b']}"
                  f"   — {r['reason'][:70]}")

    show("REAL held-out bijections (12 alias, 1 coincidental):", real)
    show("CONSTRUCTED neutral panel (3 alias, 4 coincidental):", cons)

    # ---- separation + merge outcome at the floor -------------------------------
    def band(rows, truth):
        return sorted(r["confidence"] for r in rows if r["truth"] is truth)

    print("\n" + "=" * 70)
    for label, rows in (("REAL", real), ("CONSTRUCTED", cons), ("ALL", recs)):
        al = band(rows, True)
        co = band(rows, False)
        print(f"\n{label}:")
        if al:
            print(f"  aliases       n={len(al):2}  conf {min(al):.2f}–{max(al):.2f}  "
                  f"merged@{FLOOR}: {sum(c >= FLOOR for c in al)}/{len(al)}")
        if co:
            print(f"  coincidental  n={len(co):2}  conf {min(co):.2f}–{max(co):.2f}  "
                  f"MERGED@{FLOOR}: {sum(c >= FLOOR for c in co)}/{len(co)}  <- must be 0 (corruption)")
        if al and co:
            gap = min(al) - max(co)
            print(f"  separation: weakest alias {min(al):.2f} − strongest coincidental "
                  f"{max(co):.2f} = {gap:+.2f}  ({'clean gap, ' + f'{FLOOR} sits in it' if gap > 0 and min(al) > FLOOR > max(co) else 'OVERLAP'})")

    # ---- distribution shape (all pairs) ----------------------------------------
    print("\n" + "=" * 70 + "\nDISTRIBUTION (all 20, 0.1 bins):")
    for lo in [i / 10 for i in range(10)]:
        hi = lo + 0.1
        al = sum(1 for r in recs if r["truth"] and lo <= r["confidence"] < hi or (hi == 1.0 and r["truth"] and r["confidence"] == 1.0))
        co = sum(1 for r in recs if not r["truth"] and lo <= r["confidence"] < hi or (hi == 1.0 and not r["truth"] and r["confidence"] == 1.0))
        mark = f"  <- FLOOR {FLOOR}" if lo <= FLOOR < hi else ""
        print(f"  {lo:.1f}-{hi:.1f}  alias {'#' * al:<12}{al:>2}   coinc {'#' * co:<12}{co:>2}{mark}")


if __name__ == "__main__":
    main()
