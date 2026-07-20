"""Pre-flight: prove the wiring before spending ~$9. No LLM calls.

Three things this establishes, each a failure mode that would silently corrupt
the VH - V contrast:

1. SAME FACTS. V and VH must differ in presentation only. Verified structurally
   (evidence_block(f) is a byte-identical prefix of both renderings, so the
   numbers cannot diverge) and dynamically (facts() called twice on the same
   candidate returns an equal Facts, so the runner's single call is safe to
   share between arms).

2. NO SENTINEL. The literal 4-char 'NULL' must never appear as a rendered value.
   If it does, we are showing the judge a placeholder as if it named a thing.

3. EYEBALL. Prints 3 V and 3 VH prompts in full.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import judge2  # noqa: E402
import rwd  # noqa: E402

# A rendered value looks like `foo`. The sentinel would render as `NULL`.
SENTINEL_RE = re.compile(r"`NULL`")


def check_same_facts(cands: list[dict]) -> bool:
    """Structural + dynamic proof that both arms read one facts() call."""
    ok = True
    for c in cands:
        t, a, b = c["table"], c["lhs"], c["rhs"]
        f = judge2.facts(t, a, b)

        block = judge2.evidence_block(f)
        v, vh = judge2.evidence_V(f), judge2.evidence_VH(f)

        # Structural: the shared numbers are one string, rendered once, and both
        # arms carry it verbatim as a prefix.
        if not v.startswith(block):
            print(f"  FAIL evidence_V is not evidence_block-prefixed: {t} {a}->{b}")
            ok = False
        if not vh.startswith(block):
            print(f"  FAIL evidence_VH is not evidence_block-prefixed: {t} {a}->{b}")
            ok = False

        # Dynamic: facts() is deterministic, so the runner sharing one call
        # between arms is equivalent to calling it per arm.
        if judge2.facts(t, a, b) != f:
            print(f"  FAIL facts() is not deterministic: {t} {a}->{b}")
            ok = False

        # Negative control: VH must actually differ from V, or the contrast is
        # measuring nothing.
        if v == vh:
            print(f"  FAIL V == VH (frame rendered nothing): {t} {a}->{b}")
            ok = False

        # The frame must be the clean one, not a resurrected judge2.frame().
        if "NEAR-KEY ARTIFACT" in vh or "DEGENERATE TARGET" in vh:
            print(f"  FAIL VH carries the superseded frame: {t} {a}->{b}")
            ok = False
    return ok


def check_arm_diff(cands: list[dict]) -> bool:
    """Decompose V and VH into parts and prove the ONLY differing region is the frame.

    Contract asserted here, for all 390:
        V  == evidence_block(f) + "\\n\\n" + "<one-line premise>"
        VH == evidence_block(f) + "\\n\\n" + frame_clean.frame(f)

    so everything V and VH disagree about lies inside frame_clean.frame(f), and
    the evidence_block half is byte-identical. Neither arm poses its own
    question — SYSTEM asks it once, for both.
    """
    from frame_clean import frame as clean_frame

    ok = True
    for c in cands:
        f = judge2.facts(c["table"], c["lhs"], c["rhs"])
        block = judge2.evidence_block(f)
        v, vh = judge2.evidence_V(f), judge2.evidence_VH(f)

        if vh != f"{block}\n\n{clean_frame(f)}":
            print(f"  FAIL VH != block + frame: {c['table']} {c['lhs']}->{c['rhs']}")
            ok = False

        v_tail = v[len(block) :]
        # V's tail must be a bare premise statement: no question mark, no framing.
        if not v.startswith(block):
            print(f"  FAIL V is not block-prefixed: {c['table']} {c['lhs']}->{c['rhs']}")
            ok = False
        # Neither arm may pose its own question — SYSTEM owns it, once, for both.
        # This is the confound that was caught before any call was spent.
        if "?" in v_tail:
            print(f"  FAIL V poses its own question (confound): {v_tail!r}")
            ok = False
        if "?" in vh[len(block) :]:
            print(f"  FAIL VH poses its own question (confound): {c['table']}")
            ok = False
    return ok


def check_no_sentinel(cands: list[dict]) -> bool:
    ok = True
    for c in cands:
        f = judge2.facts(c["table"], c["lhs"], c["rhs"])
        for arm, render in judge2.ARMS.items():
            hit = SENTINEL_RE.search(render(f))
            if hit:
                print(f"  FAIL sentinel rendered in {arm}: {c['table']} {c['lhs']}->{c['rhs']}")
                ok = False
    return ok


def check_frame_purity() -> bool:
    """frame_clean.frame must be pure over Facts — it must not reload a table.

    If it re-read the table it could see values the judge is not shown, and the
    contrast would no longer be presentation-only. Proven by handing it a Facts
    whose table/column identity is fabricated: a frame that reloads would raise
    or disagree; a pure one renders the fabricated numbers.
    """
    from frame_clean import frame as clean_frame

    c = rwd.exact_candidates()[0]
    f = judge2.facts(c["table"], c["lhs"], c["rhs"])
    poisoned = replace(f, n_rows=424242)
    out = clean_frame(poisoned)
    if "424242" not in out.replace(",", ""):
        print("  FAIL frame() did not render the fabricated n_rows — it may reload data")
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=762)
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args()

    cands = rwd.exact_candidates()
    print(f"candidates: {len(cands)}\n")

    print("1. same facts() feeds both arms")
    same = check_same_facts(cands)
    print(f"   {'PASS' if same else 'FAIL'} — checked all {len(cands)}\n")

    print("1b. V and VH differ ONLY by frame_clean.frame(f)")
    armdiff = check_arm_diff(cands)
    print(f"   {'PASS' if armdiff else 'FAIL'} — checked all {len(cands)}\n")

    print("2. no 'NULL' sentinel rendered as a value")
    nosent = check_no_sentinel(cands)
    print(f"   {'PASS' if nosent else 'FAIL'} — checked all {len(cands)} x both arms\n")

    print("3. frame() is pure over Facts")
    pure = check_frame_purity()
    print(f"   {'PASS' if pure else 'FAIL'}\n")

    print("4. premise holds for every candidate as rendered")
    broken = [
        c for c in cands if not judge2.holds_exactly(c["table"], c["lhs"], c["rhs"])
    ]
    print(f"   {'PASS' if not broken else 'FAIL'} — {len(broken)} broken\n")

    rng = random.Random(args.seed)
    picks = rng.sample(cands, args.show)

    # The literal diff, one pair, so the contrast is visible rather than asserted.
    c = picks[0]
    f = judge2.facts(c["table"], c["lhs"], c["rhs"])
    block = judge2.evidence_block(f)
    v, vh = judge2.evidence_V(f), judge2.evidence_VH(f)
    print("=" * 78)
    print(f"V vs VH DIFF — {c['table']} :: {c['lhs']} -> {c['rhs']}")
    print("=" * 78)
    print(f"shared evidence_block: {len(block):,} chars, byte-identical in both")
    print(f"  V  = block + {len(v) - len(block):,} chars")
    print(f"  VH = block + {len(vh) - len(block):,} chars")
    print(f"\n--- V's tail (everything after the shared block) ---\n{v[len(block):]}")
    print(f"\n--- VH's tail (everything after the shared block) ---\n{vh[len(block):]}")
    print()

    for arm in ("V", "VH"):
        for i, c in enumerate(picks, 1):
            f = judge2.facts(c["table"], c["lhs"], c["rhs"])
            print("=" * 78)
            print(f"{arm} PROMPT {i}/{args.show} — {c['table']} :: {c['lhs']} -> {c['rhs']}")
            print("=" * 78)
            print(judge2.ARMS[arm](f))
            print()

    print("=" * 78)
    print(f"SYSTEM ({len(judge2.SYSTEM)} chars):")
    print("=" * 78)
    print(judge2.SYSTEM)

    if not (same and nosent and pure and not broken):
        sys.exit(1)


if __name__ == "__main__":
    main()
