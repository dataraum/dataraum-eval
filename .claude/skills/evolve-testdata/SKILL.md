---
name: evolve-testdata
description: Add or change an injection family, fixture, or ground-truth values cleanly — injector + registry + strategy YAML + entropy_map + the eval assertion at the right tier. Use whenever eval needs test data it doesn't have.
---

# Evolve testdata: $ARGUMENTS

You are forging a new attack — the one thing the test team builds. `vendor/dataraum-testdata`
is ours; sharpening it is the job, not a contradiction of the never-fix rule (that
rule is about the *engine*). Test data changes need their own rationale — **never "so
the detector passes"** (that's Goodharting our own instrument). The deliverable is a
*family*: a clean counterpart, an injected variant with known parameters, an
`entropy_map.yaml` entry, and an assertion at the right tier — a deterministic attack
that reproduces a break on demand.

## Step 1 — Read what exists

- `vendor/dataraum-testdata/src/testdata/entropy/injectors.py` (the injector
  functions) and `entropy/registry.py` (how injections are recorded with layer,
  dimension, detector_id).
- The strategy YAMLs: eval-side `strategies/*.yaml` and testdata-side
  `config/strategies/`. An existing injector with different params often covers
  the need — check before writing a new one.
- The generator side: `canonical/finance/generators.py` is event-driven and
  closed-loop (all tables reconcile to business events). An injection that
  breaks closure must do so *knowingly* — `ground_truth.py` estimates injection
  impact on the financial metrics.
- `vendor/dataraum-testdata/CLAUDE.md` — its conventions and quality gates apply.

## Step 2 — Design the family

- **Ground truth is the point.** Every injection must yield an `entropy_map.yaml`
  entry with `detector_id`, target table/column, and exact parameters — if eval
  can't read back precisely what was injected, it can't assert anything.
- **Target what the measurement measures.** The unit_entropy lesson: a
  value-corruption injection cannot test a metadata-completeness detector.
  State, in one sentence, the causal path injection → signal the statistic sees.
- **Severity gradations, not one magic ratio.** Recall is asserted as ordering
  (clean < low < high), so prefer 2–3 severity levels over a single ratio tuned
  to cross a threshold. Ratios reflect realistic corruption.
- **Generative over hand-picked.** Sample injection values/decoys from a
  distribution (like the DAT-450 null_tokens family) rather than hard-coding the
  cases the detector already handles — hand-picked cases Goodhart the harness.
- A new *fixture need* (no injection, e.g. a data shape like events→aggregates)
  follows the same path: generator/scenario change + ground truth + a recorded
  capture, not a hand-built CSV in `scripts/`.

## Step 3 — Implement in testdata

In `vendor/dataraum-testdata`: injector + registry entry + that repo's tests
(its end-of-turn hook runs ruff + mypy + pytest). Then wire the eval strategy
YAML in `strategies/`.

**Verify injector output before trusting it.** The corrupt_dates lesson: the
strategy used strftime strings, the injector dispatched on names like
`DD/MM/YYYY`, nothing matched, and the "injection" silently injected nothing.
After generating, read actual rows of the output and confirm the corruption is
present at the expected rate, and the `entropy_map.yaml` entry matches.

```bash
# generate and inspect (example for detection-v1)
uv run python -m calibration.run -s detection-v1 --fresh --no-assert   # → data/detection-v1/ + entropy_map.yaml
```

## Step 4 — Wire the proof at the right tier

- Tier-1/2 measure tests usually consume the **recorded fixture**, not raw CSVs.
  If the new family feeds a measure under development, extend
  `scripts/capture_fixture.py` to capture what the measure consumes, refresh
  `calibration/fixtures/entropy_inputs.sqlite` (one docker run), and add the
  Tier-2 test against the loaders in `calibration/unit/fixture.py`.
- Tier-3 recall: the `entropy_map.yaml` entry is picked up by
  `calibration/test_detector_recall.py` via its `detector_id` — confirm the id
  is in `CURRENT_SLICE_DETECTORS` (or document the skip).
- New financial-metric ground truth → `ground_truth.yaml` + the relevant
  `calibration/tools/` or `/investigate` expectations.
- Agent-layer truth (FKs, table/column roles, stock/flow, cycles, folds, bus
  matrix) lives in `vendor/dataraum-testdata/src/testdata/metadata_truth.py` —
  author it from the generator/model STRUCTURE, never from what the agent
  emitted. Update the canonical truth + its remap rules, regenerate the
  committed fixture (`uv run python scripts/regen_metadata_truth.py`); Tier-1
  `test_fixture_matches_generator` binds fixture and generator so they can't
  drift.

## Step 5 — Commit in both repos

Feature branch + commit in `vendor/dataraum-testdata`; commit the strategy/test
wiring in eval. Note new families in the `entropy_eval_architecture.md` catalog
row they serve.

## Banned

- Changing a ratio, seed, or injection shape to push an existing detector over
  a threshold (that's threshold fishing through the data)
- Injections without an `entropy_map.yaml` entry or with a misleading `detector_id`
- Hand-built one-off CSVs outside the generator (no ground truth, no closure)
- Trusting an injector ran without reading the generated output
