---
name: accept
description: Product acceptance — exercise the MCP tool surface as a practitioner would, verify against ground truth, catch what code review cannot
---

# Accept: $ARGUMENTS

You are a product owner performing acceptance testing. Code review already happened. Your job is different: **does this actually work when a practitioner uses it?**

A code review checks if the code is correct. Acceptance checks if the product is useful.

## Input

$ARGUMENTS is one of:
- A strategy name (default: `detection-v1`) — run full acceptance
- `handoff` — read the handoff file and test what changed

## Step 1: Understand what to test

**If handoff mode:**
Read `vendor/dataraum-context/.claude/handoff.md`. For each pending item, identify:
- Which MCP tools are affected
- What behavior changed
- What ground truth to check against

**If full acceptance:**
All tools, all ground truth.

Load ground truth:
- `data/$0/ground_truth.yaml` — correct financial metrics
- `data/$0/entropy_map.yaml` — known injections (first ~100 lines for summary)

## Step 2: Calibration smoke test

Run the calibration tests first:
```
uv run pytest calibration/ -q --strategy $0
```

If tests fail: STOP. Report failures. These are blocking — no point exercising tools on broken output.

## Step 3: Exercise tools as a practitioner

This is the core of acceptance. Do not just call tools and check return values. Use them as a financial analyst would, asking "does this make sense?"

### look
- Call `look` on each table. Does the output tell you something useful about the data?
- Would a practitioner understand the column roles, types, distributions?
- Are there obvious problems visible in the samples that the system should have caught?

### measure
- Call `measure`. Do entropy scores align with what you know from entropy_map?
- For CLEAN columns: are scores low? High scores on clean data = false alarm = bug.
- For INJECTED columns: are scores high? Low scores on injected data = missed detection = bug.
- Does the BBN readiness make sense? Injected columns should be "investigate" or "blocked."
- Does the contract check pass/fail correctly?

### why
- For the top 3 injected columns: call `why`. Does the evidence make sense?
- Does it identify the right detector? The right problem?
- Would a practitioner understand the explanation, or is it jargon?

### query
- Ask the ground truth questions:
  1. "What is total revenue for fiscal year 2025?" (expected: from ground_truth.yaml, tolerance: 1%)
  2. "What is the DSO?" (expected: from ground_truth.yaml, tolerance: +/-1.0)
  3. "What is gross profit?" (expected: from ground_truth.yaml, tolerance: 1%)
  4. "What is revenue for March 2025?" (expected: from ground_truth.yaml, tolerance: 1%)
  5. "What is the ending AR balance?" (expected: from ground_truth.yaml, tolerance: 1%)
- Check: are assumptions declared? Is confidence provided? Is the response useful?

### run_sql
- Run a SQL query that aggregates across accounts without grouping. Are warnings emitted?
- Run a query against an injected column. Are quality warnings present?

## Step 4: Devil's advocate

Now actively try to break things:

- **Edge cases**: Query something not in the ground truth. Does the system handle uncertainty gracefully, or does it hallucinate?
- **False confidence**: Ask a question where data quality should make the answer unreliable. Does the system warn, or does it answer confidently?
- **Useless correctness**: Is any tool output technically correct but practically useless? (e.g., measure returns scores but no context about what they mean)
- **Missing connections**: If a column is injected AND queried, does the query response acknowledge the quality issue?
- **Format and UX**: Would a practitioner understand these responses without reading source code?

## Step 5: Report

Write `output/acceptance_report.yaml`:

```yaml
date: <YYYY-MM-DD>
strategy: $0
mode: handoff | full
source: vendor/dataraum-context/.claude/handoff.md  # if handoff mode

calibration:
  status: pass | fail
  failures: []  # if any

tool_acceptance:
  - tool: look
    status: pass | fail | degraded
    findings:
      - "..."
  - tool: measure
    status: pass | fail | degraded
    findings:
      - "..."
  # ... for each tool tested

ground_truth_queries:
  - id: total_revenue
    expected: 51766199.72
    actual: <value>
    deviation_pct: <pct>
    passed: true | false
    assumptions_declared: true | false
    response_useful: true | false
  # ...

devil_advocate:
  edge_cases: [<findings>]
  false_confidence: [<findings>]
  useless_correctness: [<findings>]
  missing_connections: [<findings>]

verdict: PASS | FAIL | CONDITIONAL
blocking_issues:
  - description: "..."
    severity: blocking | degraded
    affects: <tool or behavior>
observations:
  - "..."
```

## Step 6: Close the loop

- Update `vendor/dataraum-context/.claude/handoff.md`: change status of tested items from `pending` to `verified` or `failed`
- If blocking issues: create or update Linear issue with specific findings
- Print summary to user: verdict, blocking issues, key observations

## Rules

- "Tests pass" is necessary but NOT sufficient — you must USE the tools
- A tool that returns correct data in an unusable format is BROKEN
- Compare against ground_truth.yaml and entropy_map.yaml, not "looks reasonable"
- If a detector misses a known injection, it's a bug — not a design gap
- If a query returns the wrong number, that's blocking — not "within tolerance" (unless it actually is within the declared tolerance)
- Your job is to find what's wrong, not to confirm what's right
