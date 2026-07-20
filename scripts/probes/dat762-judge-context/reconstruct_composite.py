"""Forensic reconstruction of the '~42/45 class-routed composite' cited in DAT-762.

Reads ONLY the frozen dat757-channel-ablation results.json + cells.py (no writes,
no LLM calls). Recomputes:
  (a) each single channel's strict/lax total over the 45 cells
  (b) the score from picking, PER CLASS, the channel that scores best ON THAT CLASS
      (i.e. routing by the ground-truth class label = oracle routing)
to test whether (b) reproduces ~42/45 and (a)'s max reproduces 35/45.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ABL = HERE.parent / "dat757-channel-ablation"
sys.path.insert(0, str(ABL))

from cells import CELLS  # noqa: E402

CH = ("C1", "C2", "C3")


def correct(cell, verdict, direction, strict: bool) -> bool:
    """Identical to probe_ablation.correct (direction truth is always a->b)."""
    if verdict != cell.truth:
        return False
    if strict and cell.truth == "HIERARCHY":
        return direction == "a->b"
    return True


def main() -> None:
    cache = json.loads((ABL / "results.json").read_text())

    def key(cell, ch):
        return f"{cell.id}:C1" if ch == "C1" else f"{cell.id}:{ch}:r1"

    def ok(cell, ch, strict):
        r = cache[key(cell, ch)]
        return correct(cell, r["verdict"], r.get("direction"), strict)

    for strict in (True, False):
        label = "STRICT" if strict else "LAX"
        print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")

        # (a) single-channel totals over all 45 cells
        print("\n(a) single-channel totals over the 45 cells:")
        singles = {}
        for ch in CH:
            t = sum(ok(c, ch, strict) for c in CELLS)
            singles[ch] = t
            print(f"    {ch}: {t}/{len(CELLS)}")
        best_ch = max(singles, key=lambda c: singles[c])
        print(f"    best single channel = {best_ch} at {singles[best_ch]}/{len(CELLS)}")

        # (b) oracle routing: per class, pick the channel best ON THAT CLASS
        klasses = sorted({c.klass for c in CELLS}, key=lambda k: k.split("-")[0])
        print("\n(b) per-class best channel (routing by the ground-truth class label):")
        print(f"    {'class':22} {'n':>2}  {'C1':>5} {'C2':>5} {'C3':>5}   picked -> gain")
        composite = 0
        picked_channels = {}
        for kl in klasses:
            sub = [c for c in CELLS if c.klass == kl]
            per = {ch: sum(ok(c, ch, strict) for c in sub) for ch in CH}
            # tie-break in channel order C1 < C2 < C3 (cheapest-first, favours the claim)
            best = max(CH, key=lambda ch: (per[ch], -CH.index(ch)))
            composite += per[best]
            picked_channels[kl] = best
            cells_str = " ".join(f"{per[ch]:>2}/{len(sub):<2}" for ch in CH)
            print(f"    {kl:22} {len(sub):>2}  {cells_str}   {best} -> {per[best]}/{len(sub)}")
        print(f"\n    ORACLE-ROUTED COMPOSITE = {composite}/{len(CELLS)}")
        print(f"    best single channel      = {singles[best_ch]}/{len(CELLS)} ({best_ch})")
        print(f"    gap                      = +{composite - singles[best_ch]}")
        distinct = sorted(set(picked_channels.values()))
        print(f"    distinct channels the composite requires: {len(distinct)} {distinct}")
        for ch in distinct:
            kls = [k for k, v in picked_channels.items() if v == ch]
            print(f"      {ch} routes: {', '.join(kls)}")

        # per-cell oracle upper bound (routing by cell, not class) for reference
        cellwise = sum(any(ok(c, ch, strict) for ch in CH) for c in CELLS)
        print(f"\n    (reference) per-CELL oracle union upper bound = {cellwise}/{len(CELLS)}")


if __name__ == "__main__":
    main()
