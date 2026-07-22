---
name: break-detector
description: Reproduce a detector/measurement defect deterministically — a miss, an over-fire, a wrong score — at Tier 1/2 in milliseconds, prove it with a named statistic, and file it. Never fixes the engine. Use whenever a detector is wrong and you need a repro the engine team can run.
---

# Break detector: $ARGUMENTS

A detector is wrong — it misses a known injection, over-fires on clean data, or
scores something the named statistic says it shouldn't. Your job is to **reproduce
that deterministically and hand it over**, not to fix it. `vendor/dataraum-context`
is read-only from here. The deliverable is a failing millisecond test (or a wild
DB + exact steps) plus a `DAT-*` ticket. If you catch yourself editing engine code
to make the red go green, stop — that's the other team's job and doing it destroys
the reason anyone trusts a test team.

## Step 1 — Read the system, not memory

Before forming any theory:

- The catalog row in `entropy_eval_architecture.md` — the grounded statistic this
  measurement is *supposed* to compute, and its purpose. The defect is "engine
  output disagrees with this named statistic," stated precisely.
- The detector code in `vendor/dataraum-context/packages/engine/src/dataraum/entropy/`
  and its phase wiring — read the *actual* inputs it consumes and who consumes its
  output downstream, from code, not from memory or this repo's docs. You read it to
  **diagnose accurately**, so the finding names the real cause — never to edit it.
- Existing Tier-1/2 tests in `calibration/unit/` and the recall assertion in
  `calibration/test_detector_recall.py` (is the detector in `CURRENT_SLICE_DETECTORS`
  or skipped, and why?).

## Step 2 — Reproduce at the lowest tier that shows it

The value of a break is inversely proportional to how long it takes to reproduce.
Push it down:

- Pure-math wrong (ordering, calibration, edge case)? → a **Tier-1 synthetic**
  failing test. This is the strongest repro — the engine team runs it in 2 ms.
- Survives synthetic but breaks on reality? → a **Tier-2** failing test over the
  recorded fixture (`calibration/unit/fixture.py`).
- **No Tier-1/2 test demonstrates it? Write the failing one first.** A red ms-test
  *is* the reproduction; a red 10-minute pipeline run is an anecdote and costs
  tokens you don't have to spend.
- Only genuinely wiring-level defects (phase not running, records not written,
  workflow plumbing) justify a Tier-3 repro — and then the finding is about wiring,
  with the exact run and the missing artifact named.

Prove it with the **named statistic**: compute S on the same inputs and show the
engine's score diverges from what S says, by a margin, with numbers. "Feels wrong"
is not a finding.

## Step 3 — Classify the defect

Before filing, name which it is — this decides the ticket:

- **miss** — a known injection scores below clean + margin. The recall break.
- **over-fire** — clean data scores where it shouldn't (a false positive corpus is
  the sharpest evidence; a wild corpus is ideal).
- **ungrounded score** — the engine computes a boost curve / string heuristic /
  deterministic override where the catalog names a statistic. This is a *design*
  finding: cite the catalog row and the code line.
- **stale-vs-engine** — the engine's output shape moved and the oracle didn't. This
  one is **ours to fix** (the oracle is our code) — fix it, cite the engine change,
  no ticket to them.

If the miss is actually the injected family being untestable by this statistic,
that's a `/ground` question, not a defect — take it there before filing.

## Step 4 — File the finding, do not fix

The handover is a reproduction + a ticket:

- The failing Tier-1/2 test committed **in this repo** (it lives where our oracles
  live; the engine team can run `uv run pytest calibration/unit -k <name>` against
  their branch). Or, for a wild break, the corpus + the exact `stage → run` steps.
- A `DAT-*` ticket: the named statistic, the divergence with numbers, the code
  path you read, and the classification from Step 3. Quote the catalog row.
- Update the catalog row in `entropy_eval_architecture.md` only if the *finding*
  changes what we hold the engine to (e.g. a new documented over-fire mode).

Then stop. The engine team owns the fix. When their fix lands, the red test you
handed over flips green — that is how you'll know, without re-running anything
speculative.

## Anti-patterns (each has burned us)

- **Fixing the engine "while you're in there."** The single banned move. File it.
- **Threshold/ratio fishing** — moving a threshold or injection ratio until recall
  passes. Recall is ordering (injected > clean + margin), not a point score.
- **Reproducing only at Tier 3.** A slow flaky repro is a weak finding — push it down.
- **Calling a miss "out of scope" to avoid filing.** A detector that misses a known
  injection has a defect; either reproduce+file it, or take it through `/ground` to
  a recorded CUT. Never quietly weaken the assertion.
- **Burning a pipeline run to "confirm."** Confirm deterministically; spend LLM
  tokens only on a named hypothesis you can't reach any cheaper way.
