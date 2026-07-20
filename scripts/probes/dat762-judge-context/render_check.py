"""Render-check the arms with zero LLM calls — verify VR and VH carry identical
numbers and that each finding type renders. Run before any billed leg.

    uv run python scripts/probes/dat762-judge-context/render_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from channels import ARMS, SYSTEM, hypothesis_block, pair_facts  # noqa: E402
from cells import CELLS  # noqa: E402
from probe_ablation import load_all  # noqa: E402

# one cell per finding type + the classes the spike turns on
SHOW = ("D1", "F1", "H1", "I1", "A1", "C1", "L3", "K1")


def main() -> None:
    print("## loading OBTs")
    data = load_all()
    rng = np.random.default_rng(762)

    print(f"\n## system prompt ({len(SYSTEM)} chars)\n")
    print(SYSTEM)

    for cell in CELLS:
        if cell.id not in SHOW:
            continue
        print(f"\n\n{'=' * 78}\n{cell.id} [{cell.klass}] truth={cell.truth}\n  why: {cell.why}\n{'=' * 78}")
        for arm in ("N", "V", "VR", "VH"):
            body = ARMS[arm](cell, data, np.random.default_rng(762))
            print(f"\n----- arm {arm} ({len(body)} chars) -----")
            print(body if arm in ("N", "VH") else body[-1200:] if len(body) > 1200 else body)

    # VR/VH must carry identical numbers — the arms differ only in framing
    print(f"\n\n{'=' * 78}\n## VR/VH number-identity check\n{'=' * 78}")
    bad = 0
    for cell in CELLS:
        if cell.dataset.startswith("constructed"):
            continue
        obt, _, scan = data[cell.dataset]
        f = pair_facts(scan, obt, cell.a, cell.b)
        block = hypothesis_block(f, cell.a, cell.b)
        # every g3 VR reports must appear in VH's prose
        for k in ("row_g3_a_to_b", "row_g3_b_to_a"):
            if f"{f[k]:.5f}" not in block:
                print(f"  MISSING {k}={f[k]:.5f} in VH block for {cell.id}")
                bad += 1
    print(f"  pairs checked: {sum(1 for c in CELLS if not c.dataset.startswith('constructed'))}, missing numbers: {bad}")

    # token-cost estimate
    print(f"\n## approx prompt sizes (chars)")
    for arm in ("N", "V", "VR", "VH"):
        sizes = [len(ARMS[arm](c, data, np.random.default_rng(762))) for c in CELLS]
        print(f"  {arm:3} mean {int(np.mean(sizes)):>6}  max {max(sizes):>6}")


if __name__ == "__main__":
    main()
