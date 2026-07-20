"""Ceiling of asking about COLUMNS instead of PAIRS.

Nobody can answer "is dob -> surname a design FD?". Everybody can answer
"do you group by this column?". So: if the user answered ONE question per
column, perfectly, how much of the 390 resolves — and what is left over?

This is an ORACLE ceiling: it uses the labels to simulate a perfect user. It
says what the BEST a column-level UX could do is, not what a real user would do.
If the ceiling is low, the idea is dead and no UI saves it.
"""
from __future__ import annotations
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import rwd  # noqa: E402


def main() -> None:
    cands = rwd.exact_candidates()
    n_real = sum(c["meaningful"] for c in cands)
    n_junk = len(cands) - n_real
    print(f"{len(cands)} pairs: {n_real} real / {n_junk} junk (base rate {n_real/len(cands):.1%})\n")

    # --- model 1: one question per LHS column, "is this ever something you group BY?"
    lhs_groups = defaultdict(list)
    for c in cands:
        lhs_groups[(c["table"], c["lhs"])].append(c)

    dead_lhs = {k for k, v in lhs_groups.items() if not any(x["meaningful"] for x in v)}
    killed = sum(len(lhs_groups[k]) for k in dead_lhs)
    print("MODEL 1 — one question per LHS column: 'do you ever group by this?'")
    print(f"  questions asked: {len(lhs_groups)}")
    print(f"  columns answered NO: {len(dead_lhs)}")
    print(f"  junk pairs killed for free: {killed}/{n_junk} ({killed/n_junk:.1%})")
    print(f"  real pairs lost: 0 (by construction — a NO column has no real pairs)")
    surv = [c for c in cands if (c["table"], c["lhs"]) not in dead_lhs]
    sr = sum(c["meaningful"] for c in surv)
    print(f"  survivors: {len(surv)} pairs, {sr} real -> precision {sr/len(surv):.3f} "
          f"(from {n_real/len(cands):.3f})")

    # --- model 2: also ask about the RHS, "is this ever a property you'd look at?"
    rhs_groups = defaultdict(list)
    for c in cands:
        rhs_groups[(c["table"], c["rhs"])].append(c)
    dead_rhs = {k for k, v in rhs_groups.items() if not any(x["meaningful"] for x in v)}
    surv2 = [c for c in surv if (c["table"], c["rhs"]) not in dead_rhs]
    sr2 = sum(c["meaningful"] for c in surv2)
    n_q2 = len(lhs_groups) + len(rhs_groups)
    print("\nMODEL 2 — also one question per RHS column")
    print(f"  questions asked: {n_q2} (vs {len(cands)} pairs = {len(cands)/n_q2:.1f}x fewer)")
    print(f"  survivors: {len(surv2)} pairs, {sr2} real -> precision {sr2/len(surv2):.3f}")
    print(f"  real pairs lost: {n_real - sr2}")
    print(f"  junk removed: {n_junk - (len(surv2) - sr2)}/{n_junk} "
          f"({(n_junk - (len(surv2)-sr2))/n_junk:.1%})")

    # --- what's IRREDUCIBLE: both columns live, pair still junk
    resid = [c for c in surv2 if not c["meaningful"]]
    print(f"\nIRREDUCIBLE RESIDUE: {len(resid)} junk pairs whose BOTH columns appear")
    print("in some real pair. No column-level question can reach these.")
    for c in resid[:12]:
        print(f"    {c['table'].split('.')[0][:20]:20s} {c['lhs'][:24]:24s} -> {c['rhs'][:24]}")
    if len(resid) > 12:
        print(f"    ... and {len(resid)-12} more")

    # --- the honest denominator: how many questions per table?
    print("\n--- questions per table (the real onboarding burden) ---")
    for t in sorted({c["table"] for c in cands}):
        cols = {c["lhs"] for c in cands if c["table"] == t} | {
            c["rhs"] for c in cands if c["table"] == t}
        pairs = sum(1 for c in cands if c["table"] == t)
        print(f"  {t.split('.')[0][:38]:38s} {len(cols):>3} questions -> {pairs:>3} pairs")


if __name__ == "__main__":
    main()
