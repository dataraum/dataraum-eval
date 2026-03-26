---
name: investigate
description: Investigate calibration data via MCP tools — check detector recall against entropy_map and financial accuracy against ground_truth
---

# Investigate: $ARGUMENTS

You are investigating the calibration output for strategy **$0** (default: `detection-v1`).

The dataraum MCP server is connected and points at `output/$0/`. The pipeline has already run. Your job: use the MCP tools to assess data quality AND financial accuracy, then write structured findings.

## Step 1: Load ground truth

Read `data/$0/ground_truth.yaml` — the correct financial metrics (computed from clean data before injection).

Read `data/$0/entropy_map.yaml` — the known injections with target columns and detector IDs. Only read the first ~100 lines to get the injection summary (the file is large due to row indices). Focus on the `injection_id`, `target_file`, `target_column`, `detector_id`, and `parameters` fields.

## Step 2: Check data quality via MCP

Call the `get_quality` MCP tool (no arguments needed) to get entropy scores and contract status.

For each injection in entropy_map, check:
- Does the corresponding detector show a score > 0.3 for the target column?
- Record: injection_id, detector_id, target, expected score > 0.3, actual score, pass/fail

## Step 3: Check financial accuracy via MCP

Call the `query` MCP tool for these key metrics from ground_truth:

1. "What is total revenue for fiscal year 2025?"
2. "What is total expenses for fiscal year 2025?"
3. "What is the ending accounts receivable balance as of December 2025?"
4. "What is the ending cash balance as of December 2025?"
5. "Are all journal entries balanced (total debits equal total credits)?"

For each: record the question, expected value (from ground_truth), actual value from MCP, deviation percentage, and any assumptions the query agent applied.

If `query` is not available or errors, fall back to `run_sql` with direct SQL against the DuckDB tables.

## Step 4: Write findings

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
      passed: true/false

metric_accuracy:
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
      assumptions: [<list from query response>]

quality_state:
  contract_status: <from get_quality>
  top_issues: [<list of highest entropy scores>]
  fixable_issues: [<list of issues with available fix actions>]

tool_observations:
  - <any observations about tool behavior, errors, gaps>
```

## Step 5: Summarize

Print a concise summary table showing:
- Detector recall: X/Y pass
- Metric accuracy: X/Y within tolerance
- Top issues found
- Key observations about tool surface gaps (if any)
