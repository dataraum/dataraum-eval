"""Measure the stored_sign ``sign_partition`` witness reliability (DAT-875 / DAT-450).

Archetype 3. ``null_tokens`` reconstructs deterministic witnesses offline;
``temporal_behavior`` needs a real pipeline run because one of its witnesses IS an LLM.
``stored_sign`` is split down the middle:

* ``sign_partition`` — deterministic arithmetic over per-entity series. Measurable here,
  in milliseconds, against a labelled synthetic population. THIS SCRIPT.
* ``llm_claim`` — the catalogue agent's independent read. Needs a budgeted pass, exactly
  like ``temporal_behavior``'s; it is not measurable from anything frozen.

**This script does not write.** ``reliabilities.yaml`` lives in the engine repo, which is
read-only from the eval side — the older rigs' ``--write`` flag predates that charter. The
measured number goes to the engine team in the ticket, with the corpus composition below
so they can judge it rather than take it.

    uv run python scripts/calibrate_stored_sign_reliabilities.py
"""

from __future__ import annotations

from dataraum.entropy.measurements.stored_sign import (
    DEFAULT_RELIABILITIES,
    LEDGER_SIGNED,
    NATURAL_BALANCE,
    resolved_stored_sign,
)

from calibration import stored_sign_rig as rig
from calibration.reliability_rig import estimate_reliabilities

_SEEDS = range(0, 12)
_NOISE_LEVELS = (0.0, 0.3, 0.6, 0.9)


def _stratum_report() -> list[tuple[str, str, str, str]]:
    """Per stratum x truth: the partition counts and what the witness resolved."""
    rows: list[tuple[str, str, str, str]] = []
    for stratum, kwargs in rig.STRATA:
        pop = rig.make_population(stratum=stratum, seed=0, **kwargs)
        for stored in (NATURAL_BALANCE, LEDGER_SIGNED):
            part = rig.partition(pop, stored=stored)
            label = resolved_stored_sign(rig.adjudicate(pop, stored=stored))[0]
            verdict = "abstain" if label is None else ("OK" if label == stored else "WRONG")
            if not pop.discriminable:
                verdict = "undetermined"
            rows.append(
                (
                    f"{stratum}/{stored}",
                    f"n={pop.n_entities} primary={part.primary} "
                    f"mirror={part.mirror} both={part.both}",
                    str(label),
                    verdict,
                )
            )
    return rows


def main() -> None:
    labelled = rig.corpus(_SEEDS)
    discriminable = [p for p, _ in labelled if p.discriminable]

    print("stored_sign — sign_partition witness reliability (DAT-875)\n")
    print(f"  corpus       {len(labelled)} labelled populations over {len(_SEEDS)} seeds")
    print(f"               {len(rig.STRATA)} strata x 2 truth labels; composition below")
    print(f"  scored       {len(discriminable)} discriminable (both families present)")
    print(f"  excluded     {len(labelled) - len(discriminable)} single-family — the truth is")
    print("               UNDETERMINED there (the two conventions coincide), so scoring")
    print("               them would bank a coin-flip as accuracy")
    print("  estimator    Laplace-smoothed accuracy over opinionated votes")
    print("               (calibration.reliability_rig.estimate_reliabilities — the same")
    print("               estimator behind every other shipped reliability)\n")

    print("  strata:")
    for stratum, kwargs in rig.STRATA:
        print(f"    {stratum:<16} {kwargs}")
    print()

    print("  per-stratum behaviour (seed 0, family-blind event side):")
    for name, counts, label, verdict in _stratum_report():
        print(f"    {name:<34} {counts:<40} -> {label!s:<16} {verdict}")
    print()

    votes = rig.votes(labelled)
    measured = estimate_reliabilities(votes)
    opinionated = len(votes)
    correct = sum(1 for v in votes if v.correct)
    print("  MEASURED (family-blind event side, no noise):")
    print(f"    sign_partition   {measured['sign_partition']:.3f}")
    print(f"    opinionated      {opinionated} votes, {correct} correct")
    print(f"    coverage         {opinionated}/{2 * len(discriminable)} populations voted")
    print(f"    engine fallback  {DEFAULT_RELIABILITIES['sign_partition']:.3f} (placeholder)\n")

    print("  degradation under reconciliation noise — the shape that matters more than")
    print("  the scalar: a witness must lose COVERAGE, never gain confident error.")
    for noise in _NOISE_LEVELS:
        noisy = rig.votes(labelled, anchor_noise=noise)
        wrong = sum(1 for v in noisy if not v.correct)
        rel = estimate_reliabilities(noisy).get("sign_partition")
        rel_s = f"{rel:.3f}" if rel is not None else "n/a"
        print(f"    noise {noise:.1f}   votes={len(noisy):<5} wrong={wrong:<4} r={rel_s}")
    print()

    print("  CONTAMINATION (mixed-convention column — our caveat 3):")
    print("    a ledger_signed column of 200 accounts with k credit-normal accounts")
    print("    keyed the other way. The flip threshold is an ABSOLUTE COUNT, so it does")
    print("    not thin out on a bigger book:")
    big = rig.make_population(n_debit=100, n_credit=100)
    for k in (0, 1, 2, 3, 10):
        adj = rig.adjudicate(big, stored=LEDGER_SIGNED, contaminated=rig.credit_entities(big, k))
        resolved, contested = resolved_stored_sign(adj)
        state = "abstain" if resolved is None else ("OK" if resolved == LEDGER_SIGNED else "WRONG")
        print(
            f"    k={k:<3} ({k / big.n_entities:>5.1%})  -> {resolved!s:<16} "
            f"C={adj.result.conflict:.3f} U={adj.result.ignorance:.3f} contested={contested} "
            f"{state}"
        )
    print()

    print("  INVERSION CHECK (family-normalized event side — engine caveat 1):")
    inverted = rig.votes(labelled, event_side=rig.FAMILY_NORMALIZED)
    wrong = sum(1 for v in inverted if not v.correct)
    print(f"    {wrong}/{len(inverted)} opinionated votes are WRONG, i.e. accuracy")
    print(f"    {estimate_reliabilities(inverted).get('sign_partition', 0.0):.3f} on the same")
    print("    populations and the same truth. The witness is not noisy here — it is")
    print("    exactly inverted, because the partition-to-name mapping assumes an event")
    print("    side normalization that nothing in the data states.")


if __name__ == "__main__":
    main()
