"""How much evidence does each of the 390 exact candidates actually stand on?

`empty=True` candidates (no rows with both columns non-null) were already
excluded by the benchmark. But "not empty" is not "enough". If an FD holds
exactly over 2 rows, "holds exactly" is nearly vacuous.

Reads NO labels. Safe to run while the frame agent works.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import judge2  # noqa: E402
import rwd  # noqa: E402


def main() -> None:
    cands = rwd.exact_candidates()
    rows = []
    for c in cands:
        f = judge2.facts(c["table"], c["lhs"], c["rhs"])
        rows.append((c["table"], c["lhs"], c["rhs"], f.n_rows, f.a.distinct, f.rows_per_a))

    ns = sorted(r[3] for r in rows)
    print(f"n_rows over the {len(ns)} exact candidates")
    for q, label in ((0, "min"), (len(ns) // 10, "p10"), (len(ns) // 4, "p25"),
                     (len(ns) // 2, "median"), (3 * len(ns) // 4, "p75"),
                     (len(ns) - 1, "max")):
        print(f"  {label:>6}: {ns[q]:>9,}")

    print("\nhow many candidates stand on almost nothing?")
    for thr in (2, 5, 10, 50, 100, 1000):
        k = sum(1 for n in ns if n <= thr)
        print(f"  n_rows <= {thr:>5,}: {k:>3} / {len(ns)}  ({k / len(ns):.1%})")

    print("\nper table: candidates / median n_rows / min n_rows")
    for t in sorted({r[0] for r in rows}):
        sub = [r for r in rows if r[0] == t]
        sn = sorted(r[3] for r in sub)
        print(f"  {t:46s} {len(sub):>3}  med={sn[len(sn) // 2]:>9,}  min={sn[0]:>9,}")

    print("\nrows per LHS value (evidence per group) — how many are ~1?")
    rpa = sorted(r[5] for r in rows)
    for thr in (1.0, 1.5, 2.0, 5.0):
        k = sum(1 for v in rpa if v <= thr)
        print(f"  rows_per_lhs <= {thr}: {k:>3} / {len(rpa)}  ({k / len(rpa):.1%})")

    print("\nthe 10 thinnest candidates:")
    for t, a, b, n, d, rp in sorted(rows, key=lambda r: r[3])[:10]:
        print(f"  n={n:>4}  {t.split('.')[0][:22]:22s} {a[:24]:24s} -> {b[:24]}")


if __name__ == "__main__":
    main()
