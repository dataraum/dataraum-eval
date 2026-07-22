---
name: wild-corpus
description: The primary intake — take a real (non-generated) database and break the engine on it, scoring against its declared structure. Tier B of the corpus policy. Stage → frame → run → grade → read the artifacts → file findings. Never fixes the engine; never gates a build.
---

# Wild corpus: $ARGUMENTS

This is the **primary hunting ground** (default corpus: `rel-f1`). A schema we
invented, which our own agents parse cleanly, mainly proves we write schemas well.
Real data with structural ground truth is the antidote — the whole point is to break
the engine on data it didn't get to design. Take the database, run it, and go find
what breaks.

**The contract (law doc, corpus-policy section):** structural truth only — declared
FKs, types, time columns. Never invent labels for someone else's schema; never
promote ML task labels to ground truth. The result is a **scoreboard, never a
build-break** — a miserable result is a **finding**, filed, not a red build. And
nothing here fixes the engine: `vendor/dataraum-context` is read-only.

## Step 1 — Stage

Corpora live in `corpora/` (gitignored; NC-licensed sets are fetched at run time,
never committed). RelBench exports sit in `corpora/relbench/<ds>/` with `schema.json`
+ `tables/*.parquet`.

```bash
uv run python scripts/stage_wild_corpus.py <name>
```

This copies parquets flat into `data/<name>/` and derives a structural
`metadata_truth.yaml` from `schema.json` (`relationships` ← declared fkeys,
`semantic_roles.timestamp` ← time_col, `tier: wild`). All other truth sections stay
empty **on purpose** — the corresponding oracles stand down.

For a new corpus, extend `stage_wild_corpus.py` with its layout; keep the
declared-structure-only rule. Fill the curation checklist as you onboard: license
(redistributable vs internal-use-only), duplicates, leakage, ground-truth provenance.

## Step 2 — Frame (only for a new domain)

A corpus in an unframed domain cannot reach the pipeline — exactly one vertical ships
(`finance`), and `semantic_per_column` fails loud on `_adhoc`.
`scripts/frame_wild_vertical.py` writes typed Concept rows for the corpus's domain
(see the `rel-f1` → MOTORSPORT example in it).

A vertical is **product configuration, not ground truth** — nothing is graded against
these concepts. Name a vocabulary; do not assert the engine must reproduce your
reading of someone else's schema.

## Step 3 — Run (budget it)

```bash
uv run python -m calibration.runner <name> --pipeline-only --vertical <name>
```

This is a real-LLM run — the one expensive step. Name what you're hunting before you
start it (the token-budget rule), background it, and line up the grading prep
meanwhile. Don't idle on it; don't re-run it speculatively.

## Step 4 — Grade

```bash
uv run pytest calibration/ --strategy <name> -q
```

Then read `output/<name>/oracle_coverage.json`: which oracles graded, which skipped,
and why. On a wild corpus most truth sections are empty by construction — verify the
skips are the *expected* stand-downs, not a silent regression. Report:

- FK recall/precision vs the declared topology (`test_relationships_e2e.py` —
  corpus-generic, zero literals).
- Detector fire-rates as a **false-positive corpus** — bands will read "NEW — no
  band" against the finance-keyed `clean_bands.yaml`; the raw fire-rate is the
  interesting number. A detector firing all over a clean wild schema is an over-fire
  finding.

## Step 5 — Read the artifacts, not just the asserts

The best breaks come from reading the prompt/response dumps and the persisted
`current_*` rows, not from assertions firing (DAT-834/835/836/839 all came out of
that). Read like a hostile practitioner — the engine is hiding something in there.
Look for: prompt-size blowups, silently dropped columns or types, candidate-graph
pathologies (value overlap on surrogate keys), free-text labels drifting where the
schema gave no anchor.

## Step 6 — Verdict + file findings

Write a short verdict: does the system generalize off its own schema, and what broke.
Every miss becomes one of:

- an **engine bug** ticket (`DAT-*`) — with a deterministic repro pushed as low as it
  goes (a wild break that reproduces on a small slice is far stronger than "the whole
  10-minute run looked off").
- a **generator-backlog attack** — the authenticity loop: make the synthetic corpus
  (`/evolve-testdata`) stress what the wild data stressed, so next time it's a Tier-1
  repro.

Record corpus-level results where the run left them (`output/<name>/`). The
scoreboard **never gates a build**, and nothing here patches the engine.

## Banned

- Fixing the engine because a wild corpus exposed a defect — file it (read-only rule).
- Inventing semantic labels, roles, or cycles for a schema someone else declared.
- Promoting ML task labels (churn/LTV targets) to metadata ground truth.
- Committing NC-licensed data, or parking corpora under `data/` (where `make clean`
  eats them).
- Turning a wild-corpus miss into a relaxed oracle — it is a finding, filed.
- Hard ceilings/caps to make a pathological corpus pass (DAT-834's lesson: use the
  named bounded objects — SCCs, circuit rank — never a limit).
