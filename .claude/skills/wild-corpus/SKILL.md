---
name: wild-corpus
description: Run a real (non-generated) database through the pipeline and score it against its declared structure — Tier B of the corpus policy. Stage → frame → run → grade → read the artifacts → file findings. Scoreboard, never a build-break.
---

# Wild corpus: $ARGUMENTS

You are running a Tier-B corpus (default: `rel-f1`) through the real pipeline.
The point is to falsify "we're great": a schema we invented, which our agents
parse cleanly, mainly proves we write schemas well. Real data with structural
ground truth is the antidote to testing only what we thought to inject.

**The contract (law doc, corpus-policy section):** structural truth only —
declared FKs, types, time columns. Never invent labels for someone else's
schema; never promote ML task labels to ground truth. The result is a
**scoreboard, never a build-break** — miserable failure is a finding.

## Step 1 — Stage

Corpora live in `corpora/` (gitignored; NC-licensed sets are fetched at run
time, never committed). RelBench exports sit in `corpora/relbench/<ds>/` with
`schema.json` + `tables/*.parquet`.

```bash
uv run python scripts/stage_wild_corpus.py <name>
```

This copies parquets flat into `data/<name>/` and derives a structural
`metadata_truth.yaml` from `schema.json` (`relationships` ← declared fkeys,
`semantic_roles.timestamp` ← time_col, `tier: wild`). All other truth sections
stay empty **on purpose** — the corresponding oracles stand down.

For a new corpus, extend `stage_wild_corpus.py` with its layout; keep the
declared-structure-only rule. Fill in the curation checklist as you onboard:
license (redistributable vs internal-use-only), duplicates, leakage, ground-truth
provenance.

## Step 2 — Frame (only for a new domain)

A corpus in an unframed domain cannot reach the pipeline — exactly one vertical
ships (`finance`), and `semantic_per_column` fails loud on `_adhoc`.
`scripts/frame_wild_vertical.py` writes typed Concept rows for the corpus's
domain (see the `rel-f1` → MOTORSPORT example in it).

A vertical is **product configuration, not ground truth** — nothing is graded
against these concepts. Name a vocabulary; do not assert the engine must
reproduce your reading of someone else's schema.

## Step 3 — Run

```bash
uv run python -m calibration.runner <name> --pipeline-only --vertical <name>
```

Background it (minutes, real LLM calls); line up the grading prep meanwhile.

## Step 4 — Grade

```bash
uv run pytest calibration/ --strategy <name> -q
```

Then read `output/<name>/oracle_coverage.json`: which oracles graded, which
skipped, and why. On a wild corpus most truth sections are empty by
construction — verify the skips are the *expected* stand-downs, not a silent
regression. Report:

- FK recall/precision vs the declared topology (`test_relationships_e2e.py` —
  corpus-generic, zero literals).
- Detector fire-rates as a **false-positive corpus** — bands will read
  "NEW — no band" against the finance-keyed `clean_bands.yaml`; the raw
  fire-rate is the interesting number, not a failure.

## Step 5 — Read the artifacts, not just the asserts

The bugs this lane exists for come from reading the prompt/response dumps and
the persisted `current_*` rows, not from assertions firing (DAT-834/835/836/839
all came out of that). Look for: prompt-size blowups, silently dropped columns
or types, candidate-graph pathologies (value overlap on surrogate keys),
free-text labels drifting where the schema gave no anchor.

## Step 6 — Verdict + findings

Write a short verdict: does the system generalize off its own schema, and what
broke. Every miss becomes either an engine bug ticket (DAT-*) or a generator
backlog item (the authenticity loop: make the synthetic corpus stress what the
wild data stressed). Record corpus-level results where the run left them
(`output/<name>/`); the scoreboard never gates a build.

## Banned

- Inventing semantic labels, roles, or cycles for a schema someone else declared
- Promoting ML task labels (churn/LTV targets) to metadata ground truth
- Committing NC-licensed data, or parking corpora under `data/` (where
  `make clean` eats them)
- Turning a wild-corpus miss into a relaxed oracle — it is a finding, filed
- Hard ceilings/caps to make a pathological corpus pass (DAT-834's lesson: use
  the named bounded objects — SCCs, circuit rank — never a limit)
