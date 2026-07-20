"""DAT-762 — cost-class breakdown of the dev-leg ablation (cache-only, zero API calls).

Re-grades the frozen 45-cell inventory (dat757-channel-ablation/cells.py) against
the cached arm verdicts in results_dev.json under a COST-CLASS metric instead of
plain accuracy:

  FALSE IDENTITY  asserted MERGE     where truth != MERGE   (silent wrong numbers)
  MISSED IDENTITY truth == MERGE     asserted otherwise
  FALSE DRILL     asserted HIERARCHY where truth == REJECT   (a bad line in a list)
  MISSED DRILL    truth == HIERARCHY asserted REJECT         (real structure destroyed)

Arms N/V/VR/VH are reduced by majority-of-3-reps; ties (no >=2 agreement) are
carried as an explicit "TIE" verdict and never broken silently. C1 is the
deterministic mechanical baseline (probe_ablation.c1_verdict), single rep.

Run: python3 scripts/probes/dat762-judge-context/analyze_cost_classes.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dat757-channel-ablation"))

from cells import CELLS  # noqa: E402  (frozen inventory — read-only)

RESULTS = HERE / "results_dev.json"
ARMS = ("N", "V", "VR", "VH")
VERDICTS = ("MERGE", "HIERARCHY", "ROLE", "REJECT")
REPS = (1, 2, 3)


def majority(verdicts: list[str]) -> tuple[str, str]:
    """Majority verdict + a strength tag. No silent tie-breaking."""
    counts = Counter(verdicts).most_common()
    top, n = counts[0]
    if n == 1:  # all distinct -> genuine tie
        return "TIE", "/".join(verdicts)
    return top, f"{n}/{len(verdicts)}"


def load() -> tuple[dict, dict]:
    cache = json.loads(RESULTS.read_text())
    # asserted[cell_id][arm] = (verdict, strength); C1 is single-rep
    asserted: dict[str, dict[str, tuple[str, str]]] = {}
    strength: dict[str, dict[str, str]] = {}
    for cell in CELLS:
        asserted[cell.id] = {}
        strength[cell.id] = {}
        c1 = cache[f"{cell.id}:C1"]
        asserted[cell.id]["C1"] = c1["verdict"]
        strength[cell.id]["C1"] = "det"
        for arm in ARMS:
            vs = [cache[f"{cell.id}:{arm}:r{r}"]["verdict"] for r in REPS]
            v, s = majority(vs)
            asserted[cell.id][arm] = v
            strength[cell.id][arm] = s
    return asserted, strength


def cost_classes(cells: list, asserted: dict, arm: str) -> dict[str, list]:
    """The four cost buckets for one arm over the given cell population."""
    out = {"false_identity": [], "missed_identity": [], "false_drill": [], "missed_drill": []}
    for c in cells:
        a = asserted[c.id][arm]
        if a == "MERGE" and c.truth != "MERGE":
            out["false_identity"].append(c)
        if c.truth == "MERGE" and a != "MERGE":
            out["missed_identity"].append(c)
        if a == "HIERARCHY" and c.truth == "REJECT":
            out["false_drill"].append(c)
        if c.truth == "HIERARCHY" and a == "REJECT":
            out["missed_drill"].append(c)
    return out


def confusion(cells: list, asserted: dict, arm: str) -> dict:
    m = {t: Counter() for t in VERDICTS}
    for c in cells:
        m[c.truth][asserted[c.id][arm]] += 1
    return m


def render_confusion(cells: list, asserted: dict, arm: str) -> str:
    m = confusion(cells, asserted, arm)
    cols = list(VERDICTS)
    if any(m[t]["TIE"] for t in VERDICTS):
        cols.append("TIE")
    lines = [f"| truth \\ asserted | {' | '.join(cols)} | n |", "|" + "---|" * (len(cols) + 2)]
    for t in VERDICTS:
        n = sum(m[t].values())
        if not n:
            continue
        lines.append(f"| **{t}** | " + " | ".join(str(m[t][a]) for a in cols) + f" | {n} |")
    return "\n".join(lines)


def population_note(cells: list) -> str:
    tc = Counter(c.truth for c in cells)
    return ", ".join(f"{t}={tc[t]}" for t in VERDICTS if tc[t])


def report(cells: list, asserted: dict, title: str) -> None:
    n = len(cells)
    n_merge = sum(c.truth == "MERGE" for c in cells)
    n_hier = sum(c.truth == "HIERARCHY" for c in cells)
    n_rej = sum(c.truth == "REJECT" for c in cells)
    print(f"\n\n# {title}")
    print(f"\nPopulation: {n} cells ({population_note(cells)})")

    print("\n## Cost-class summary\n")
    print("| arm | FALSE IDENTITY | MISSED IDENTITY | FALSE DRILL | MISSED DRILL |")
    print("|---|---|---|---|---|")
    print(f"| | /{n - n_merge} non-MERGE | /{n_merge} MERGE | /{n_rej} REJECT | /{n_hier} HIERARCHY |")
    buckets = {}
    for arm in ("C1", *ARMS):
        b = cost_classes(cells, asserted, arm)
        buckets[arm] = b
        print(
            f"| {arm} | {len(b['false_identity'])} | {len(b['missed_identity'])} "
            f"| {len(b['false_drill'])} | {len(b['missed_drill'])} |"
        )

    for key, label in (
        ("false_identity", "FALSE IDENTITY (asserted MERGE, truth != MERGE)"),
        ("missed_identity", "MISSED IDENTITY (truth == MERGE, asserted otherwise)"),
        ("false_drill", "FALSE DRILL (asserted HIERARCHY, truth == REJECT)"),
        ("missed_drill", "MISSED DRILL (truth == HIERARCHY, asserted REJECT)"),
    ):
        print(f"\n## {label}\n")
        for arm in ("C1", *ARMS):
            items = buckets[arm][key]
            if not items:
                print(f"- **{arm}**: 0")
                continue
            print(f"- **{arm}**: {len(items)}")
            for c in items:
                got = asserted[c.id][arm]
                print(
                    f"    - `{c.id}` [{c.klass}] truth={c.truth} asserted={got} "
                    f"— ({c.a}, {c.b}) [{c.dataset}]"
                )

    print("\n## Confusion matrices (truth x asserted)")
    for arm in ("C1", *ARMS):
        print(f"\n### {arm}\n")
        print(render_confusion(cells, asserted, arm))


def main() -> None:
    asserted, strength = load()

    print("# DAT-762 cost-class breakdown — cache-only re-grade of results_dev.json")
    print(f"\nSource: `{RESULTS.name}` (585 cached entries, zero new API calls)")
    print("Inventory: `dat757-channel-ablation/cells.py` (45 frozen cells)")

    # --- majority / tie accounting -----------------------------------------
    print("\n## Rep reduction (majority-of-3)\n")
    print("| arm | 3/3 unanimous | 2/3 majority | ties (all-distinct) |")
    print("|---|---|---|---|")
    for arm in ARMS:
        s = Counter(strength[c.id][arm] for c in CELLS)
        print(f"| {arm} | {s['3/3']} | {s['2/3']} | {sum(v for k, v in s.items() if '/' not in k)} |")
    ties = [(c.id, arm, strength[c.id][arm]) for c in CELLS for arm in ARMS
            if asserted[c.id][arm] == "TIE"]
    print(f"\nTies requiring a break: **{len(ties)}**" + (f" — {ties}" if ties else " (none)"))
    print("C1 is deterministic (single rep, no reduction).")

    # --- full population ----------------------------------------------------
    report(list(CELLS), asserted, "Part 1 — ALL 45 cells")

    # --- routed population --------------------------------------------------
    routed = [c for c in CELLS if asserted[c.id]["C1"] != "REJECT"]
    dropped = [c for c in CELLS if asserted[c.id]["C1"] == "REJECT"]
    report(routed, asserted, "Part 2 — ROUTED population only (C1 verdict != REJECT)")

    print(f"\n## Cells NOT routed (C1 == REJECT): {len(dropped)}/45\n")
    for c in dropped:
        flag = "  <-- truth is MERGE/HIERARCHY, dropped before any judge" \
            if c.truth in ("MERGE", "HIERARCHY") else ""
        print(f"- `{c.id}` [{c.klass}] truth={c.truth} — ({c.a}, {c.b}){flag}")

    # --- premise checks -----------------------------------------------------
    print("\n\n# Premise / contradiction flags\n")
    # HIERARCHY asserted where truth == MERGE or ROLE (not counted as false drill)
    for arm in ("C1", *ARMS):
        odd = [c for c in CELLS
               if asserted[c.id][arm] == "HIERARCHY" and c.truth in ("MERGE", "ROLE")]
        if odd:
            print(f"- {arm}: asserted HIERARCHY on non-REJECT non-HIERARCHY truth "
                  f"({len(odd)}): " + ", ".join(f"{c.id}(truth={c.truth})" for c in odd))
    # MERGE asserted where truth == ROLE — the role-collapse case
    for arm in ("C1", *ARMS):
        rc = [c for c in CELLS if asserted[c.id][arm] == "MERGE" and c.truth == "ROLE"]
        if rc:
            print(f"- {arm}: FALSE IDENTITY on ROLE truth ({len(rc)}): "
                  + ", ".join(c.id for c in rc))


if __name__ == "__main__":
    main()
