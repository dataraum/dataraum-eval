---
name: deliver
description: Produce a business deliverable via MCP tools and validate against ground truth expected values
---

# Deliver: $0 / $1

You are producing a business deliverable for strategy **$0** (default: `detection-v1`), deliverable **$1** (default: `annual_summary`).

The dataraum MCP server is connected and points at `output/$0/`. Your job: use the MCP tools as a practitioner would — assess quality, address issues, then produce the deliverable and validate it against expected values.

## Step 1: Load the deliverable spec

Read `deliverables/$1.yaml` — the expected output definition with metrics, tolerances, and quality requirements.

If `output/$0/findings.yaml` exists (from a prior `/investigate` run), read it to understand the current quality state. Otherwise, proceed without it.

## Step 2: Start session and assess quality

Call `begin_session` to initialize the session with contract context.

Call `measure` to understand the current data quality state — measurement points, BBN readiness, pipeline status.

Identify issues that could affect the deliverable's metrics. For each:
- Is it documented in the measure response?
- Would teaching the system about it improve metric accuracy?
- Or should it be accepted with a documented assumption?

## Step 3: Teach or accept issues

For issues where providing knowledge would help (column properties, acceptances, domain rules):
- Call `teach` with the appropriate type and parameters.
- Record what was taught and why.

For issues without a teaching path or where the issue is inherent to the data:
- Document the assumption: what's wrong, why it's accepted, impact on metrics.

Do NOT try to address every issue — only those that affect the deliverable's metrics. The goal is a correct deliverable, not a perfect quality score.

## Step 4: Produce the deliverable

For each metric in the deliverable spec:
- Call `query` with the question.
- Extract the numeric answer.
- Compare against the expected value using the specified tolerance (tolerance_pct or tolerance_abs).
- Record: metric id, question, expected, actual, deviation, pass/fail, confidence, assumptions applied.

For boolean metrics (like journal_balanced):
- Call `query` or `run_sql` to verify.
- Record pass/fail.

## Step 5: Write the delivery report

Write results to `output/$0/delivery_$1.yaml`:

```yaml
strategy: $0
deliverable: $1
timestamp: <ISO 8601>

quality_actions:
  teachings:
    - type: <teach type>
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
      expected: 51766199.72
      actual: <value>
      deviation_pct: <pct>
      tolerance_pct: 1.0
      passed: true/false
      confidence: <from query response>
      assumptions: [<from query response>]

quality_requirements:
  - id: issues_surfaced
    passed: true/false
    detail: <how many issues were identified>
  - id: assumptions_declared
    passed: true/false
    detail: <were assumptions present on query responses>

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
