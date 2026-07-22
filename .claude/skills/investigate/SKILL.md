---
name: investigate
description: Hunt a completed calibration run for breakage via the direct engine reads — check detector recall against entropy_map and financial accuracy against ground_truth, then file findings. Never fixes the engine.
---

# Investigate: $ARGUMENTS

You are hunting the calibration output for strategy **$0** (default: `detection-v1`)
for defects, and filing what you find. You are the hostile practitioner: assume the
engine got something wrong and go prove it. Nothing here is a fix — every red or
suspicious result becomes a **finding** (a `DAT-*` ticket or a teach scenario),
never a relaxed oracle and never an engine patch.

The pipeline has already run (the sidecar at `output/$0/calibration_run.json` proves
it; if it is missing, stop and say so — **do not trigger a run** to satisfy this
skill; that burns tokens for no named hypothesis). You read the run through the
read-only tools in `calibration/tools/`:

```bash
uv run python -m calibration.tools.look $0 [table]            # schema + profiles
uv run python -m calibration.tools.measure $0 [--target t.c]  # scores + readiness + evidence
uv run python -m calibration.tools.sql $0 "SELECT ..."        # read-only SQL on the lake
```

## Step 1 — Load ground truth (what SHOULD be true)

- `data/$0/ground_truth.yaml` — the correct financial metrics (computed from clean
  data before injection).
- `data/$0/entropy_map.yaml` — the known injections (target column + `detector_id` +
  params). Read only the first ~100 lines for the injection summary; the file is
  large because of row indices.
- `data/$0/metadata_truth.yaml` — the agent-layer truth (FK topology, roles,
  stock/flow, cycles) the e2e oracles grade against.
- `output/$0/oracle_coverage.json` if present — which oracles graded, which skipped,
  and why. **Skips are how a run goes green without finding anything** — verify every
  skip is an expected stand-down, not a silent regression. An oracle that stood down
  because a read helper swallowed an error is itself a finding.

## Step 2 — Look at the data

`look $0` (no table) for the overview — tables, row counts, time axes, enriched
views. Then `look $0 <table>` on 2–3 tables with known injections: does the metadata
make sense, are the injected columns visibly corrupted? You are looking for the
engine quietly getting it wrong, not for confirmation it's fine.

## Step 3 — Measure entropy, hunt the misses and over-fires

`measure $0` for all column-scoped detector scores and the per-intent readiness
(`ready` / `investigate` / `blocked` — a deterministic loss rollup; the BBN is gone,
DAT-442). For each injection in entropy_map:

- Is there a score for the target column + expected detector? **A missing or below-
  clean score is a recall miss — a finding.**
- What is the worst-intent readiness? Injected columns should reach `investigate`
  or `blocked`; one that stays `ready` is a finding.

Also hunt the other direction: **clean columns that scored or banded** — over-fires
are often the sharper finding. `measure $0 --target <table.column>` drills into a
column's evidence: every entropy object, its witness claims, and the
`claim_witnesses` provenance (which witness said what, at what reliability).

## Step 4 — Check financial accuracy against ground truth

YOU write the SQL — the retired `query` tool wrapped an LLM, and that judgment is
yours now. Use `sql` for the metrics in `ground_truth.yaml`, at minimum: total
revenue FY2025, total expenses FY2025, ending AR at Dec 2025, ending cash at Dec
2025, and whether all journal entries balance (debits = credits).

Mind the trial-balance semantics: the trial balance is **periodic, not cumulative** —
balance-sheet items need the right aggregation over periods, and a column's
`temporal_behavior` evidence (stock vs flow) tells you whether SUM is even
meaningful. When the entropy evidence flags a column you're querying, that's the
engine warning you — factor it into your confidence, and if a flagged column
produces a wrong number the engine didn't guard, that's a finding.

## Step 5 — Write the findings dossier

Write `output/$0/findings.yaml`:

```yaml
strategy: $0
timestamp: <ISO 8601>
ground_truth_source: data/$0/ground_truth.yaml
entropy_map_source: data/$0/entropy_map.yaml

detector_recall:
  total: <N>
  passed: <N>
  failed: <N>
  details:
    - injection_id: NULL-0001
      detector_id: null_ratio
      target: journal_lines.cost_center
      expected_min: 0.3
      actual: <score>
      readiness: <ready|investigate|blocked>
      passed: true/false

metric_accuracy:
  total: <N>
  passed: <N>
  failed: <N>
  details:
    - id: total_revenue
      question: "What is total revenue for fiscal year 2025?"
      sql: "<the statement you ran>"
      expected: 51766199.72
      actual: <value>
      deviation_pct: <pct>
      tolerance_pct: 1.0
      passed: true/false
      assumptions: [<the judgments you applied>]

quality_state:
  overall_readiness: <worst band across columns>
  columns_blocked: <N>
  columns_investigate: <N>
  top_issues: [<highest scoring measurement points>]

findings:                      # the point — machine-read by calibration/findings.py
  - id: <slug>
    kind: miss | over-fire | ungrounded-score | wrong-metric | stale-eval
    title: <one line>
    vertical: finance          # the (vertical, dataset) this was found on — never assume finance
    dataset: $0
    target: <table.column or metric id>
    detector_id: <id>          # required for miss/over-fire/ungrounded-score
    named_statistic: <KS | orphan-rate | Cramer's V | ...>   # no finding without one (charter)
    evidence: <numbers + the read that shows it>
    disposition: DAT-ticket | teach-scenario | ours-to-fix | graduate
    source: $0                 # where it surfaced (corpus / DAT-#)
```

## Step 6 — Triage every red before you file

Classify each red or suspicious result — the disposition decides where it goes:

- **engine bug** — the pipeline persisted something wrong → a `DAT-*` ticket, with a
  deterministic repro if you can push it to Tier 1/2 (that's `/break-detector`).
- **stale eval** — the engine's output shape moved and the oracle didn't → **ours to
  fix** (the oracle is our code), citing the engine change. Not a ticket to them.
- **LLM variance** — within the measured band / xfail(strict=False) territory →
  record, don't file, don't patch.
- **testdata drift** — generator and committed truth disagree → regenerate via
  `/evolve-testdata`, don't hand-edit.

A red oracle is a filed finding, never a relaxed assertion. When triage is
ambiguous, **read the prompt/response artifacts** — DAT-829/830/834 were found there,
not in assertion output. And never patch the engine to make the red go green — file it.
