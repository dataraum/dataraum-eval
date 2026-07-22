---
name: ground
description: The ground-first kill gate as a procedure — name an established statistic, probe separation on fixtures in milliseconds, verdict BUILDABLE (file it) or CUT (file "don't build this"). Run BEFORE the engine builds any new measurement, or before forging a new attack.
---

# Ground: $ARGUMENTS

You are evaluating a measurement hypothesis in 2 ms, before anyone spends a sprint.
The default outcome is **CUT**. Survival requires a named established statistic
separating the injected family from natural variation by a margin, in a millisecond
probe — before any engine code, any pipeline run, any LLM call.

This is the cheapest, highest-leverage thing the test team does, and it cuts two
ways — neither is a build order, because this repo never builds the engine:

- **The engine wants to build measurement X?** Probe it here first. If its named
  statistic can't separate signal from noise, that's a **finding filed before the
  sprint is wasted** — "don't build this, here's the math."
- **You want a new attack?** Same gate — an injection family that doesn't reproduce
  a break deterministically is not an attack.

## Step 0 — Name the statistic, or stop

State the hypothesis as a **refutable claim**: "statistic S separates family F
from natural variation on real financial data by margin M."

S must be a *named, established* method: KS, Wasserstein, mutual information,
Cramér's V, KL, JSD, PSI, Kruskal–Wallis, Nigrini MAD, autocorrelation/variance-ratio, …
If you cannot name one, the idea is not ready to probe — say so and stop.
Inventing a score formula here is the boost-curve failure mode; don't.

Check `entropy_eval_architecture.md`'s catalog first: has this idea (or this
wall) been tried? `temporal_drift`, `outlier_rate`, `slice_variance`,
bimodality-`unit_consistency`, and the DAT-459 trajectory signature all died at
this gate — read why before re-walking a dead path.

## Step 1 — Sketch the contract

Three lines, per the measurement contract in `entropy_eval_architecture.md`:
**Purpose** (what decision does it serve a practitioner?), **Fix/teach** (what
action closes it?), **Earns its place?** If it enables no fix/teach and is not
genuine context for a query/aggregation decision, CUT now — a separating
statistic with no consumer is still noise.

## Step 2 — Write the probe (adversarially)

One directory: `scripts/probes/<ticket-or-slug>/`. Never at `scripts/` root.

Structure each probe like the DAT-459 probes — the docstring states:
- **CLAIM UNDER TEST (to refute)** — the exact claim with quoted expected bands
- **THE ATTACK** — the most dangerous false-positive/false-negative case you can
  construct against it (trending flows, heavy tails, seasonal patterns, small N,
  clustered decoys — real financial data's natural variation is the adversary)

Three legs:
- **(a) REAL** — the recorded fixture (`calibration/unit/fixture.py` loaders over
  `calibration/fixtures/entropy_inputs.sqlite`): compute S on the actual clean
  and injected families.
- **(b) SYNTHETIC worst case** — the attack shapes at realistic sizes (T~12
  periods, real row counts), including low-noise variants.
- **(c) GAP** — report the separation: clean-family p90/p95/max vs injected
  lower edge, AUC, or margin. Numbers, not adjectives.

Comparing multiple candidate statistics? Same fixture, same legs, one table of
margins — a clean comparison, not sequential tweaking until one fires.

Run it: `uv run python scripts/probes/<slug>/probe_<lens>.py`. Milliseconds, no
docker, no pipeline, no LLM.

## Step 3 — Verdict, filed as a finding either way

- **Separation by a margin → BUILDABLE.** The statistic can work. Write the contract
  entry in the `entropy_eval_architecture.md` catalog and file it to the engine team
  as a finding — "this measurement is grounded, here's the probe and the margin,
  build it." If it's *our* new attack, this is the green light to `/evolve-testdata`
  the injection family + the Tier-1/2 oracles. Either way, the engine implementation
  is the engine team's job, not this repo's.
- **Overlap, or margin only under unrealistic parameters → CUT.** One grounded
  attempt is the budget. Record the result in the catalog (statistic tried, numbers,
  why it fails — like the existing CUT rows) as a filed "don't build this," then
  delete the probe directory. The recorded *why* is the deliverable; the scripts are
  not.

## Banned in this skill

- Boost curves, score remapping, or any invented formula to manufacture separation
- Tuning the injection ratio so the statistic passes
- A second "attempt" that is the first attempt with fished thresholds
- Running the pipeline, docker, or an LLM to answer a pure-math question
