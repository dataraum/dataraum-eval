"""DAT-762 — confidence field re-analysis, CACHE-ONLY (zero LLM calls).

Reads results_dev.json (the frozen dev-leg cache) and the frozen DAT-757 instrument.
Settles whether section 12's two statements ("14/14 VH misgrades are high" and
"high 0.83 / medium 0.45 / low 0.00") are computed over different populations.

    uv run python scripts/probes/dat762-judge-context/analyze_confidence.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from channels import CORE_ARMS, hypothesis_block, pair_facts  # noqa: E402
from cells import CELLS, Cell  # noqa: E402
from probe_ablation import correct, load_all  # noqa: E402

REPS = (1, 2, 3)
CONFS = ("high", "medium", "low", "None")
RESULTS = HERE / "results_dev.json"


def ok(cell: Cell, r: dict) -> bool:
    return correct(cell, r["verdict"], r.get("direction"), True)  # strict — section 12's grain


def conf(r: dict) -> str:
    return str(r.get("confidence"))


def main() -> None:
    cache = json.loads(RESULTS.read_text())
    res = {(c.id, a, r): cache[f"{c.id}:{a}:r{r}"] for c in CELLS for a in CORE_ARMS for r in REPS}
    print(f"cache: {len(cache)} entries | gradings analysed: {len(res)} "
          f"({len(CELLS)} cells x {len(CORE_ARMS)} arms x {len(REPS)} reps)")
    print("ZERO LLM calls — read-only over results_dev.json\n")

    # ---- 1. confidence distribution per arm --------------------------------
    print("=" * 78)
    print("1. CONFIDENCE DISTRIBUTION PER ARM (n=135 each)")
    print("=" * 78)
    print(f"{'arm':5} {'n':>4}  " + "  ".join(f"{c:>16}" for c in CONFS))
    for arm in CORE_ARMS:
        cnt = Counter(conf(res[(c.id, arm, r)]) for c in CELLS for r in REPS)
        n = sum(cnt.values())
        cells_ = "  ".join(f"{f'{cnt[c]:3} ({100*cnt[c]/n:5.1f}%)':>16}" for c in CONFS)
        print(f"{arm:5} {n:>4}  {cells_}")
    print()
    for arm in CORE_ARMS:
        cnt = Counter(conf(res[(c.id, arm, r)]) for c in CELLS for r in REPS)
        non_high = sum(v for k, v in cnt.items() if k != "high")
        print(f"  {arm:3}: non-high gradings = {non_high}/135 ({100*non_high/135:.1f}%)")

    # cell-level: does VH ever express non-high on ANY cell/rep?
    print()
    print("  Cells where the arm ever emitted non-high (any rep):")
    for arm in CORE_ARMS:
        ids = sorted({c.id for c in CELLS for r in REPS if conf(res[(c.id, arm, r)]) != "high"})
        print(f"    {arm:3}: {len(ids):2} cells {ids}")

    # ---- 2. calibration per arm, then pooled -------------------------------
    print()
    print("=" * 78)
    print("2. CALIBRATION PER ARM (P(correct | confidence)), then POOLED")
    print("=" * 78)

    def calib(pairs: list[tuple[str, bool]]) -> dict[str, tuple[int, int]]:
        t: dict[str, list[int]] = {c: [0, 0] for c in CONFS}
        for cf, good in pairs:
            t[cf][0 if good else 1] += 1
        return {c: (v[0], v[1]) for c, v in t.items()}

    def show(label: str, pairs: list[tuple[str, bool]]) -> None:
        t = calib(pairs)
        parts = []
        for cf in CONFS:
            g, b = t[cf]
            n = g + b
            parts.append(f"{cf}: " + (f"{g/n:.2f} ({g}/{n})" if n else "-- (0/0)"))
        print(f"  {label:26} " + "   ".join(f"{p:20}" for p in parts))

    for arm in CORE_ARMS:
        show(f"arm {arm}", [(conf(res[(c.id, arm, r)]), ok(c, res[(c.id, arm, r)]))
                           for c in CELLS for r in REPS])
    print()
    show("POOLED (all 4 arms, 540)", [(conf(res[(c.id, a, r)]), ok(c, res[(c.id, a, r)]))
                                      for c in CELLS for a in CORE_ARMS for r in REPS])
    show("POOLED starved (N,V,VR)", [(conf(res[(c.id, a, r)]), ok(c, res[(c.id, a, r)]))
                                     for c in CELLS for a in ("N", "V", "VR") for r in REPS])
    print()
    print("  Where do the non-high gradings live? (denominator provenance)")
    for cf in ("medium", "low", "None"):
        per = {a: sum(1 for c in CELLS for r in REPS if conf(res[(c.id, a, r)]) == cf)
               for a in CORE_ARMS}
        tot = sum(per.values())
        if tot:
            print(f"    {cf:7} total={tot:3}  " + "  ".join(
                f"{a}={per[a]:2} ({100*per[a]/tot:4.1f}%)" for a in CORE_ARMS))

    # ---- 3. verify "14/14 VH misgrades are confidence=high" ----------------
    print()
    print("=" * 78)
    print("3. VH MISGRADES — count and confidence breakdown")
    print("=" * 78)
    vh_bad = [(c, r, res[(c.id, "VH", r)]) for c in CELLS for r in REPS
              if not ok(c, res[(c.id, "VH", r)])]
    print(f"  VH incorrect gradings: {len(vh_bad)}/135")
    print(f"  confidence breakdown : {dict(Counter(conf(e) for _, _, e in vh_bad))}")
    print()
    for c, r, e in vh_bad:
        got = e["verdict"] + (f"/{e.get('direction')}" if e.get("direction") else "")
        print(f"    {c.id:3} r{r} [{c.klass:19}] got {got:16} want {c.truth:9} conf={conf(e)}")
    # same for every arm, for comparison
    print()
    print("  For comparison — misgrades x confidence, per arm:")
    for arm in CORE_ARMS:
        bad = [res[(c.id, arm, r)] for c in CELLS for r in REPS if not ok(c, res[(c.id, arm, r)])]
        print(f"    {arm:3}: {len(bad):3} wrong  " + str(dict(Counter(conf(e) for e in bad))))

    # ---- 4. frame attribution ---------------------------------------------
    print()
    print("=" * 78)
    print("4. FRAME ATTRIBUTION (VH) — which frame rendered, how it scored")
    print("=" * 78)
    data = load_all()
    frame_of: dict[str, str] = {}
    for cell in CELLS:
        if cell.dataset.startswith("constructed"):
            frame_of[cell.id] = "no joint stats (K)"
            continue
        obt, _, scan = data[cell.dataset]
        blk = hypothesis_block(pair_facts(scan, obt, cell.a, cell.b), cell.a, cell.b)
        if "determine EACH OTHER" in blk:
            f = "frame_bidirectional"
        elif "no determination in either direction" in blk:
            f = "frame_no_finding"
        else:
            f = "frame_determination"
        # near-copy is an ADDITIVE frame — record whether it also rendered
        if "same-domain near-copy" in blk:
            f += " (+near_copy)"
        frame_of[cell.id] = f

    frames = sorted({f.split(" (+")[0] for f in frame_of.values()})
    print()
    print(f"  {'frame (primary)':24} {'cells':>5} {'gradings':>9} {'wrong':>6} {'err%':>6}  conf on wrong")
    for fr in frames:
        sub = [c for c in CELLS if frame_of[c.id].split(" (+")[0] == fr]
        grad = [(c, r, res[(c.id, "VH", r)]) for c in sub for r in REPS]
        bad = [(c, r, e) for c, r, e in grad if not ok(c, e)]
        cb = dict(Counter(conf(e) for _, _, e in bad)) if bad else {}
        print(f"  {fr:24} {len(sub):>5} {len(grad):>9} {len(bad):>6} "
              f"{100*len(bad)/len(grad):>5.1f}%  {cb}")
        if bad:
            per_cell = Counter(c.id for c, _, _ in bad)
            print(f"      wrong cells: {dict(per_cell)}  (of {[c.id for c in sub]})")
    print()
    print("  near-copy add-on frame rendered on:",
          sorted(c.id for c in CELLS if "+near_copy" in frame_of[c.id]))
    print()
    print(f"  {'frame':40} {'VH correct / n':>16}")
    for fr in sorted({f for f in frame_of.values()}):
        sub = [c for c in CELLS if frame_of[c.id] == fr]
        grad = [(c, r, res[(c.id, "VH", r)]) for c in sub for r in REPS]
        good = sum(1 for c, _, e in grad if ok(c, e))
        print(f"  {fr:40} {f'{good}/{len(grad)}':>16}   ({good/len(grad)*3:.2f}/{len(sub)} cell-equiv)")

    # ---- 5. within-arm abstain-below-high ---------------------------------
    print()
    print("=" * 78)
    print("5. ABSTAIN BELOW high — retained n and errors among retained, PER ARM")
    print("=" * 78)
    print(f"  {'arm':5} {'all n':>6} {'all err':>8} {'all err%':>9}   "
          f"{'retained':>9} {'ret err':>8} {'ret err%':>9}   {'abstained':>10} {'err abstained':>14}")
    for arm in CORE_ARMS:
        grad = [(c, res[(c.id, arm, r)]) for c in CELLS for r in REPS]
        n = len(grad)
        err = sum(1 for c, e in grad if not ok(c, e))
        keep = [(c, e) for c, e in grad if conf(e) == "high"]
        kerr = sum(1 for c, e in keep if not ok(c, e))
        drop = [(c, e) for c, e in grad if conf(e) != "high"]
        derr = sum(1 for c, e in drop if not ok(c, e))
        print(f"  {arm:5} {n:>6} {err:>8} {100*err/n:>8.1f}%   "
              f"{len(keep):>9} {kerr:>8} {100*kerr/len(keep) if keep else 0:>8.1f}%   "
              f"{len(drop):>10} {f'{derr}/{len(drop)}' if drop else '0/0':>14}")
    print()
    print("  Error mass removed by abstaining below high, per arm:")
    for arm in CORE_ARMS:
        grad = [(c, res[(c.id, arm, r)]) for c in CELLS for r in REPS]
        err = sum(1 for c, e in grad if not ok(c, e))
        derr = sum(1 for c, e in grad if conf(e) != "high" and not ok(c, e))
        print(f"    {arm:3}: {derr}/{err} of the arm's errors sit below high"
              + (f" = {100*derr/err:.0f}% of its error mass" if err else ""))


if __name__ == "__main__":
    main()
