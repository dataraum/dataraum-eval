---
name: deliver
description: Produce a business deliverable from a completed calibration run and validate it against ground truth expected values
---

# Deliver: $0 / $1

You are producing a business deliverable for strategy **$0** (default: `detection-v1`), deliverable **$1** (default: `annual_summary`).

The pipeline has already run (sidecar at `output/$0/calibration_run.json`; if missing, stop and say so — never trigger a run yourself). You read the run through the direct tools (the MCP server is retired, ADR-0002):

```bash
uv run python -m calibration.tools.look $0 [table]            # schema + profiles
uv run python -m calibration.tools.measure $0 [--target t.c]  # scores + readiness + evidence
uv run python -m calibration.tools.sql $0 "SELECT ..."        # read-only SQL on the lake
```

Use them as a practitioner would — assess quality, address issues, then produce the deliverable and validate it against expected values.

## Step 1: Load the deliverable spec

Read `deliverables/$1.yaml` — the expected output definition with metrics, tolerances, and quality requirements.

If `output/$0/findings.yaml` exists (from a prior `/investigate` run), read it to understand the current quality state. Otherwise, proceed without it.

## Step 2: Assess quality

Run `measure $0` to understand the data quality state — detector scores and the loss-rollup intent readiness (`ready` / `investigate` / `blocked`; the Bayesian network is gone, DAT-442).

Identify issues that could affect the deliverable's metrics. For each:
- Is it visible in the measure output (a high score, a non-ready band)?
- Would teaching the system about it improve metric accuracy?
- Or should it be accepted with a documented assumption?

## Step 3: Teach or accept issues

The teach paths are the runner helpers (each applies a config-overlay teaching and RE-RUNS the affected slice, promoting a fresh head):

- `calibration.runner.teach_null_value_and_rerun` — declare a sentinel/null token
- `calibration.runner.teach_unit_and_rerun` — declare a column's unit
- `calibration.runner.teach_concept_property_and_rerun` — correct an ontology concept property

Teaching triggers a real pipeline slice (LLM calls, minutes) — apply a teach only when it plausibly changes a deliverable metric, and say so before running it. Record what was taught and why.

For issues without a teaching path or where the issue is inherent to the data:
- Document the assumption: what's wrong, why it's accepted, impact on metrics.

Do NOT try to address every issue — only those that affect the deliverable's metrics. The goal is a correct deliverable, not a perfect quality score.

## Step 4: Produce the deliverable

For each metric in the deliverable spec, YOU write the SQL (`sql $0 "..."`) — the retired `query` tool wrapped an LLM, and that judgment is yours now:

- Extract the numeric answer.
- Compare against the expected value using the specified tolerance (tolerance_pct or tolerance_abs).
- Check the entropy evidence for every column your SQL aggregates (`measure $0 --target t.c`): a stock-vs-flow conflict on a SUMmed column, a unit conflict, a null-semantics flag — these change either your SQL or your confidence. The trial balance is PERIODIC, not cumulative.
- Record: metric id, question, sql, expected, actual, deviation, pass/fail, assumptions applied.

For boolean metrics (like journal_balanced): verify via `sql` and record pass/fail.

## Step 5: Write the delivery report

Write results to `output/$0/delivery_$1.yaml`:

```yaml
strategy: $0
deliverable: $1
timestamp: <ISO 8601>

quality_actions:
  teachings:
    - type: <teach helper used>
      target: <column or table>
      params: <what was taught>
      reason: <why>
  assumptions_made:
    - issue: <what's wrong>
      target: <column or table>
      reason: <why accepted>
      impact: <how it affects the deliverable>

metrics:
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

quality_requirements:
  - id: issues_surfaced
    passed: true/false
    detail: <how many issues were identified>
  - id: assumptions_declared
    passed: true/false
    detail: <was every non-trivial SQL judgment recorded as an assumption>

verdict: PASS/FAIL
failure_reasons: [<if FAIL, list which metrics or requirements failed>]

tool_observations:
  - <observations about tool behavior, what worked, what didn't>
```

## Step 6: Summarize

Print a summary:
- Verdict: PASS or FAIL
- Metrics: X/Y within tolerance
- Teachings applied: N
- Assumptions made: N
- If FAIL: what specifically went wrong, and what would need to change in the tool surface or pipeline to fix it
