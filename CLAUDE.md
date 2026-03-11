# DataRaum Eval

Calibration and evaluation harness for the DataRaum entropy detection system. Uses known data injections from `dataraum-testdata` as ground truth to measure detector recall and precision.

## Architecture

This repo does NOT contain production code. It contains:
1. **Calibration tests** — deterministic assertions against ground truth
2. **Agent prompts** — evaluation agents that use MCP tools to assess analytical correctness

### Repos

| Repo | Role |
|------|------|
| `dataraum-testdata` | Generates data with known injections + `entropy_map.yaml` + `ground_truth.yaml` |
| `dataraum-context` | The pipeline being evaluated (detectors, phases, fixes) |
| `dataraum-eval` (this) | Connects the two — runs pipeline, measures results against ground truth |

### Data Flow

```
testdata generate → CSVs + entropy_map.yaml + ground_truth.yaml
    ↓
dataraum run → pipeline output (metadata.db, data.duckdb)
    ↓
calibration tests → compare detector scores against entropy_map
    ↓
eval agents (MCP) → query results, verify metrics, apply fixes
```

## Calibration Tests

### Detector Recall
For each injection in `entropy_map.yaml`, assert the corresponding detector produced an elevated score (> threshold) for the affected column.

### Detector Precision
On clean data (no injections), assert all detector scores are below threshold.

### Fix Loop
Apply a fix for a detected injection → re-run affected phase → assert score drops.

### Ground Truth Metrics
Use `ground_truth.yaml` to verify computed metrics (revenue, DSO, FCF) are within tolerance.

## Eval Agents

Agents use the DataRaum MCP server to evaluate the system. They are Claude Code sessions with specific prompts.

### Critic Agent
- Runs pipeline on test data
- Uses `get_quality` to check entropy scores
- Uses `query` to compute metrics and compare against ground truth
- Reports findings

### Fix Agent
- Reads Critic findings
- Uses MCP fix tool (or CLI `dataraum fix`) to apply fixes
- Verifies scores drop after fix

### Entry Criteria
Before the eval agents can work, `dataraum-context` must expose:
- [ ] `dataraum fix` CLI command (standalone, not just PAUSE mode)
- [ ] MCP `apply_fix` tool (programmatic fix application)

## Running

```bash
# Generate test data
cd ../dataraum-testdata
uv run testdata generate --scenario month-end-close --strategy clean --output ../dataraum-eval/data/clean --seed 42
uv run testdata generate --scenario month-end-close --strategy medium --output ../dataraum-eval/data/medium --seed 42

# Run pipeline on both
cd ../dataraum-context
dataraum run ../dataraum-eval/data/clean --output ../dataraum-eval/output/clean --vertical finance
dataraum run ../dataraum-eval/data/medium --output ../dataraum-eval/output/medium --vertical finance

# Run calibration
cd ../dataraum-eval
uv run pytest calibration/ -v
```

## Current State

As of 2026-03-11:
- **Detector recall**: 3/15 injections detected (20%)
- **Detectors that work**: outlier_rate, benford, null_ratio
- **Detectors that don't find known injections**: type_fidelity, unit_entropy, temporal_entropy, business_meaning, relationship_entropy, temporal_drift, dimensional_entropy, derived_value, derived_value_consistency, cross_table_consistency
- **Detectors that can't run** (missing upstream analyses): temporal_drift, dimensional_entropy, derived_value, column_quality, dimension_coverage
