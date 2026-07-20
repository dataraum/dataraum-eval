"""Plumbing smoke test — no LLM calls, no labels read.

Checks that facts() actually runs over every table in the slice before we spend
2,340 API calls finding out it doesn't. Deliberately does NOT print the
`meaningful` field: this file is safe to read while the frame agent works.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import judge2  # noqa: E402
import rwd  # noqa: E402


def main() -> None:
    cands = rwd.exact_candidates()
    print(f"candidates: {len(cands)}")

    tables = sorted({c["table"] for c in cands})
    print(f"tables: {len(tables)}\n")

    t0 = time.time()
    sizes = []
    for t in tables:
        first = next(c for c in cands if c["table"] == t)
        try:
            f = judge2.facts(t, first["lhs"], first["rhs"])
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {t}: {type(exc).__name__}: {exc}")
            continue
        v = judge2.evidence_V(f)
        sizes.append(len(v))
        print(
            f"  ok  {t:46s} n={f.n_rows:>9,} "
            f"cols={len(f.table_cols):>2} V={len(v):>5}ch"
        )
    print(f"\nall tables profiled in {time.time() - t0:.1f}s")
    if sizes:
        print(f"V prompt chars: min={min(sizes)} max={max(sizes)}")

    # full-slice cost shape: how long to profile all 390?
    t0 = time.time()
    ok = 0
    for c in cands:
        try:
            judge2.facts(c["table"], c["lhs"], c["rhs"])
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {c['table']} {c['lhs']}->{c['rhs']}: {exc}")
    print(f"\nprofiled {ok}/{len(cands)} candidates in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
