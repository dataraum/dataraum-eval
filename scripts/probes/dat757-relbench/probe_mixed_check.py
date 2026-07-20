"""DAT-757 RelBench fold — follow-up: does the RFI effect floor block the skew residue?

rel-salt exposed a boundary the synthetic E-grid could not: on a 99.4%-dominant
dependent (doc__DISTRIBUTIONCHANNEL), row-g3 <= 0.01 is VACUOUS and, at n=214k,
perm-p+BH accepts every weak-but-real dependence (~40 extras). The E-grid's nulls
were independent, so BH looked strictly better there and 16266 recommended it
REPLACE RFI>0.05. This probe grades the mixed gate (row-g3 + RFI effect floor,
pair-count aliases + RFI) on the same three real OBTs to test the amended claim:
"the stack needs BOTH an information effect floor AND significance" — i.e. RFI
blocks the skew mass-assert without losing exact-truth recall.

Run:  uv run python -u scripts/probes/dat757-relbench/probe_mixed_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "dat757-g3-wide"))
sys.path.insert(0, str(Path(__file__).parent))

from fdlib import MIN_DISTINCT_DIMENSION, alias_decision, edge_decision, scan_pairs  # noqa: E402
from probe_fold_grade import SPECS, build_obt, grade, truth_tables  # noqa: E402


def main() -> None:
    for name in ("rel-f1", "rel-hm", "rel-salt"):
        base = Path("corpora/relbench") / name
        print(f"\n# {name}")
        obt, group = build_obt(base, SPECS[name])
        cols = list(obt.columns)
        scan = scan_pairs(obt, cols)
        truth_e, truth_a = truth_tables(scan, cols)
        eligible = [c for c in cols if scan.singles[c] >= MIN_DISTINCT_DIMENSION]
        for gate in ("eng", "mixed"):
            got_e, got_a = set(), set()
            for i, a in enumerate(eligible):
                for b in eligible[i + 1 :]:
                    if edge_decision(scan, a, b, gate):
                        got_e.add((a, b))
                    elif edge_decision(scan, b, a, gate):
                        got_e.add((b, a))
                    if alias_decision(scan, a, b, gate):
                        got_a.add((a, b))
            print(grade(gate, scan, group, truth_e, truth_a, got_e, got_a, False))
            if gate == "mixed":
                grade(gate, scan, group, truth_e, truth_a, got_e, got_a, True)


if __name__ == "__main__":
    main()
