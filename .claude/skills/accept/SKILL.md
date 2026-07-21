---
name: accept
description: Product acceptance — exercise the eval tool surface as a practitioner would, verify against ground truth, catch what code review cannot
---

# Accept: $ARGUMENTS

You are a product owner performing acceptance testing. Code review already happened. Your job is different: **does this actually work when a practitioner uses it?**

A code review checks if the code is correct. Acceptance checks if the product is useful.

The engine's MCP server is retired (ADR-0002; the cockpit is the product's client). What you exercise here is the eval read surface over the engine-as-library — the same live functions the product reads through:

```bash
uv run python -m calibration.tools.look $0 [table]            # schema + profiles
uv run python -m calibration.tools.measure $0 [--target t.c]  # scores + readiness + evidence
uv run python -m calibration.tools.sql $0 "SELECT ..."        # read-only SQL on the lake
```

## Input

$ARGUMENTS is one of:
- A strategy name (default: `detection-v1`) — run full acceptance
- `changes` — test what recently changed in the engine

## Step 1: Understand what to test

**If changes mode:**
The engine retired its `.claude/handoff.md` journal — change context lives in
its code, ADRs, and Jira. Read the recent engine commits
(`git -C vendor/dataraum-context log --oneline -20`) and their DAT-* tickets.
For each change, identify:
- Which read surface or pipeline behavior is affected
- What behavior changed
- What ground truth to check against

**If full acceptance:**
The whole surface, all ground truth.

Load ground truth:
- `data/$0/ground_truth.yaml` — correct financial metrics
- `data/$0/entropy_map.yaml` — known injections (first ~100 lines for summary)

## Step 2: Calibration smoke test

Run the calibration tests first:
```
uv run pytest calibration/ -q --strategy $0
```

If tests fail: STOP. Report failures. These are blocking — no point exercising tools on broken output.

## Step 3: Exercise the surface as a practitioner

This is the core of acceptance. Do not just run tools and check return values. Use them as a financial analyst would, asking "does this make sense?"

### look
- Run `look $0`, then `look $0 <table>` on each table. Does the output tell you something useful about the data?
- Would a practitioner understand the column roles, types, distributions?
- Are there obvious problems visible in the profiles that the system should have caught?

### measure
- Run `measure $0`. Do entropy scores align with what you know from entropy_map?
- For CLEAN columns: are scores low? High scores on clean data = false alarm = bug.
- For INJECTED columns: are scores high? Low scores on injected data = missed detection = bug.
- Does the loss-rollup readiness make sense? Injected columns should be `investigate` or `blocked`.

### measure --target (the why-equivalent)
- For the top 3 injected columns: run `measure $0 --target <table.column>`. Does the evidence make sense?
- Does it identify the right detector? The right problem? Do the witness claims (`claim_witnesses`) tell a coherent story — who disagreed with whom, and why did the score follow?
- Would a practitioner understand the explanation, or is it jargon?

### sql (you write the SQL — that judgment moved from the retired query tool to you)
- Answer the ground truth questions:
  1. "What is total revenue for fiscal year 2025?" (expected: from ground_truth.yaml, tolerance: 1%)
  2. "What is the DSO?" (expected: from ground_truth.yaml, tolerance: +/-1.0)
  3. "What is gross profit?" (expected: from ground_truth.yaml, tolerance: 1%)
  4. "What is revenue for March 2025?" (expected: from ground_truth.yaml, tolerance: 1%)
  5. "What is the ending AR balance?" (expected: from ground_truth.yaml, tolerance: 1%)
- For each: before trusting your own SQL, check the entropy evidence on the columns you aggregate. Did the surface warn you where it should have (stock-vs-flow on a SUM, unit conflicts, null semantics)? The trial balance is PERIODIC, not cumulative — does the evidence surface that?

## Step 4: Devil's advocate

Now actively try to break things:

- **Edge cases**: Query something not in the ground truth. Does the surface give you what you need to handle uncertainty, or does it leave you guessing?
- **False confidence**: Find a question where data quality should make the answer unreliable. Does the evidence warn you, or would a practitioner confidently compute a wrong number?
- **Useless correctness**: Is any tool output technically correct but practically useless? (e.g., scores with no context about what they mean)
- **Missing connections**: If a column is injected AND needed for a metric, does the evidence chain (`measure --target`) actually connect the dots?
- **Format and UX**: Would a practitioner understand these outputs without reading source code?

## Step 5: Report

Write `output/acceptance_report.yaml`:

```yaml
date: <YYYY-MM-DD>
strategy: $0
mode: changes | full
source: <engine commits/tickets tested>  # if changes mode

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
  - tool: sql
    status: pass | fail | degraded
    findings:
      - "..."

ground_truth_queries:
  - id: total_revenue
    expected: 51766199.72
    actual: <value>
    deviation_pct: <pct>
    passed: true | false
    evidence_warned_where_needed: true | false
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

- If blocking issues: report them with specific findings (Jira lives at DAT-*)
- Print summary to user: verdict, blocking issues, key observations

## Rules

- "Tests pass" is necessary but NOT sufficient — you must USE the surface
- A tool that returns correct data in an unusable format is BROKEN
- Compare against ground_truth.yaml and entropy_map.yaml, not "looks reasonable"
- If a detector misses a known injection, it's a bug — not a design gap
- If your SQL returns the wrong number, decide honestly whether the surface failed you (no warning where evidence existed) or the data did — the first is blocking
- Your job is to find what's wrong, not to confirm what's right
