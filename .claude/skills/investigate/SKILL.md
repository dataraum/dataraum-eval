---
name: investigate
description: Investigate calibration output via the direct engine reads — check detector recall against entropy_map and financial accuracy against ground_truth
---

# Investigate: $ARGUMENTS

You are investigating the calibration output for strategy **$0** (default: `detection-v1`).

The pipeline has already run (the sidecar at `output/$0/calibration_run.json` proves it; if it is missing, stop and say so — do not trigger a run). The engine's MCP server is retired (ADR-0002); you read the run through the direct tools in `calibration/tools/`:

```bash
uv run python -m calibration.tools.look $0 [table]            # schema + profiles
uv run python -m calibration.tools.measure $0 [--target t.c]  # scores + readiness + evidence
uv run python -m calibration.tools.sql $0 "SELECT ..."        # read-only SQL on the lake
```

Your job: assess data quality AND financial accuracy, then write structured findings.

## Step 1: Load ground truth

Read `data/$0/ground_truth.yaml` — the correct financial metrics (computed from clean data before injection).

Read `data/$0/entropy_map.yaml` — the known injections with target columns and detector IDs. Only read the first ~100 lines to get the injection summary (the file is large due to row indices). Focus on the `injection_id`, `target_file`, `target_column`, `detector_id`, and `parameters` fields.

Read `data/$0/metadata_truth.yaml` — the agent-layer truth (FK topology, table/column roles, stock/flow, cycles) the e2e oracles grade against.

If `output/$0/oracle_coverage.json` exists (written by the last pytest pass), read it: which oracles graded, which skipped, and why. Skips are how a run goes green without checking anything — verify every skip is an expected stand-down, not a silent regression.

## Step 2: Look at the data

Run `look` with no table for the full overview — tables, row counts, identified time axes, enriched views.

For 2-3 tables that have known injections, run `look $0 <table>` to see column profiles. Check: does the metadata make sense? Are injected columns showing signs of corruption?

## Step 3: Measure entropy

Run `measure $0` for all column-scoped detector scores and the loss-rollup readiness (per-intent `ready` / `investigate` / `blocked` — the Bayesian network is gone, readiness is a deterministic loss rollup; DAT-442).

For each injection in entropy_map, check:
- Is there a score for the target column + expected detector?
- Is the score > 0.3?
- What is the worst intent readiness for the column? (should be `investigate` or `blocked` for injected columns)
- Record: injection_id, detector_id, target, expected score > 0.3, actual score, readiness, pass/fail

Run `measure $0 --target <table.column>` to drill into a specific column's evidence: every entropy object with its witness claims plus the `claim_witnesses` provenance (which witness said what, with what reliability).

## Step 4: Check financial accuracy

YOU write the SQL now — the retired `query` tool wrapped an LLM, and that judgment is yours. Use `sql` for these key metrics from ground_truth:

1. "What is total revenue for fiscal year 2025?"
2. "What is total expenses for fiscal year 2025?"
3. "What is the ending accounts receivable balance as of December 2025?"
4. "What is the ending cash balance as of December 2025?"
5. "Are all journal entries balanced (total debits equal total credits)?"

Mind the trial-balance semantics: the trial balance is PERIODIC, not cumulative — balance-sheet items need the right aggregation over periods, and a column's `temporal_behavior` evidence (stock vs flow) tells you whether SUM is even meaningful. When the entropy evidence flags a column you are querying, factor that into your confidence.

For each: record the question, the SQL you ran, expected value (from ground_truth), actual value, deviation percentage, and the assumptions you applied.

## Step 5: Write findings

Write the results to `output/$0/findings.yaml` with this structure:

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

tool_observations:
  - <any observations about tool behavior, errors, gaps>
```

## Step 6: Summarize

Print a concise summary table showing:
- Detector recall: X/Y pass
- Metric accuracy: X/Y within tolerance
- Readiness: X blocked, Y investigate, Z ready
- Oracle accounting: X graded, Y skipped (each skip named with its reason)
- Top issues found
- Key observations about tool surface gaps (if any)

## Triage rule

Classify every red or suspicious result before proposing anything:
- **engine bug** — the pipeline persisted something wrong → file a DAT-* ticket
- **stale eval** — the engine's output shape moved and the oracle didn't → fix the oracle, citing the engine change
- **LLM variance** — within the measured band / xfail(strict=False) territory → record, don't patch
- **testdata drift** — generator and committed truth disagree → regenerate, don't hand-edit

A red oracle is a bug ticket or a teach scenario, never a relaxed assertion.
When triage is ambiguous, read the prompt/response artifacts — that is where
DAT-829/830/834 were actually found, not in assertion output.
