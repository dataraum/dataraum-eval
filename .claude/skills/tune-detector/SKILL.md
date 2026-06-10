---
name: tune-detector
description: Fix or tune an entropy detector/measurement — read the engine subsystem first, reproduce at Tier 1/2 in milliseconds, change one thing, e2e only as the final gate. Use whenever a detector misses, over-fires, or needs a scoring change.
---

# Tune detector: $ARGUMENTS

You are changing detector/measurement behavior in the engine. The dev loop is
Tier 1/2 (milliseconds, no docker). The 10-minute pipeline appears exactly once,
at the end, as a gate. If you find yourself wanting to re-run the pipeline to
"see if it works now," you are in the hack-and-compile loop — stop and come back
to this procedure.

## Step 1 — Read the system, not memory

Before forming any theory:

- The catalog row in `entropy_eval_architecture.md` — the grounded statistic this
  measurement is *supposed* to compute, its purpose, and its fix/teach. If your
  planned change deviates from the named statistic, that's a `/ground` question
  first, not a tuning task.
- The detector code in `vendor/dataraum-context/packages/engine/src/dataraum/entropy/`
  and its phase wiring (`pipeline.yaml` / detect steps). Read the *actual* inputs
  it consumes and who consumes its output downstream — from code, not from
  memory files or this repo's docs.
- Existing Tier-1/2 tests in `calibration/unit/` and the recall assertion in
  `calibration/test_detector_recall.py` (is the detector in
  `CURRENT_SLICE_DETECTORS` or skipped?).
- `vendor/dataraum-context/packages/engine/CLAUDE.md` — its conventions apply to
  every engine edit.

## Step 2 — Reproduce at the lowest tier that shows the problem

- Pure-math wrong (ordering, calibration, edge case)? → Tier-1 synthetic test.
- Survives synthetic but breaks on reality? → Tier-2 test over the recorded
  fixture (`calibration/unit/fixture.py`).
- **No Tier-1/2 test demonstrates the problem? Write one first.** A failing
  ms-test is the reproduction; a failing 10-minute pipeline run is an anecdote.
- Only genuinely wiring-level problems (phase not running, records not written,
  workflow plumbing) justify going straight to Tier 3 — and then the fix is
  wiring, not scoring.

## Step 3 — Change one thing

Make the change in the engine. One variable at a time. Then:

```bash
uv run pytest calibration/unit -q                                  # Tier 1+2, ms
uv --directory vendor/dataraum-context/packages/engine run pytest --testmon tests -q
```

Iterate **here**, at millisecond speed, until green.

## Step 4 — Gate, once

When Tier 1/2 are green and the engine suite passes, run the one integration
gate for the affected strategy (`make calibrate` / `make calibrate-typing`, or
the stepwise targets). Background the run and line up other work — don't idle,
and don't loop on it. Recall regressions elsewhere in the suite are part of the
verdict: a detector change that breaks another detector's recall is not done.

## Step 5 — Commit like an engine change

Feature branch inside `vendor/dataraum-context`, commit the green work, update
`.claude/handoff.md` there. Update the catalog row in
`entropy_eval_architecture.md` if the statistic or its calibration changed.

## Anti-patterns (each has burned us)

- **Threshold/ratio fishing** — moving the threshold or the injection ratio
  until recall passes. Recall is ordering (injected > clean + margin), not a
  point score.
- **Boost curves** — any invented amplification formula. If raw statistic values
  feel "too small," the framing is wrong, not the curve.
- **String heuristics** — pattern-matching names/values where the catalog says
  statistic or LLM judgment.
- **Deterministic patches over LLM judgments** — xfail(strict=False) and pooling
  handle non-determinism; overrides are banned (entropy *is* disagreement).
- **Editing test data to make the detector pass** — testdata changes need their
  own rationale via `/evolve-testdata`.
- **Calling a miss "out of scope"** — a detector that misses a known injection
  has a bug (engine CLAUDE.md). Either fix it or take it through `/ground` to a
  recorded CUT; don't quietly weaken the assertion.
