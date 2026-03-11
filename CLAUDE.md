# DataRaum Eval

Calibration harness for the DataRaum entropy detection and fix system.

## What This Repo Does

Tests whether the pipeline's entropy detectors and fix loop work correctly,
using known data injections from `dataraum-testdata` as ground truth.

### Repos

| Repo | Role |
|------|------|
| `dataraum-testdata` | Generates closed-loop financial data with known injections (`entropy_map.yaml`) and pre-computed metrics (`ground_truth.yaml`) |
| `dataraum-context` | The pipeline: phases, detectors, fix system, MCP server |
| `dataraum-eval` (this) | Calibration tests and evaluation agents |

## Concepts

### Quality Zones

The pipeline runs in progressive quality zones. Each zone ends at a quality
gate where entropy is measured and fixes can be applied.

- **Zone 1 (Foundation):** import → typing → statistics → relationships → semantic → `quality_review` gate. 9 detectors run here.
- **Zone 2 (Enrichment):** enriched_views → correlations → slicing → drift analysis → `analysis_review` gate (proposed). 5 additional detectors.
- **Zone 3 (Interpretation):** entropy (Bayesian network) → entropy_interpretation, graph_execution. Re-measures all detectors. Least mature.

See `spec/` for detailed zone specifications.

### Entropy Detectors

Detectors measure uncertainty about data quality. Score 0 = confident, 1 = maximum uncertainty. Each detector declares which analyses it needs (`required_analyses`) — it runs at the earliest zone where those analyses are available.

### Fix System

Fixes are user/agent decisions applied through three interpreters (config, metadata, data). All Zone 1 detectors declare fix schemas. The scheduler applies fixes, resets affected phases, re-runs, and re-measures at the gate. The infrastructure is complete; the MCP `apply_fix` tool is not yet exposed.

## Calibration

### What We Test

1. **Detection calibration** — detectors fire on injected data, stay quiet on clean data. Pure data, no LLM
2. **Fix calibration** — LLM-in-the-loop: agent proposes fix, fix applied, score drops. Builds on (1)
3. **Ground truth metrics** — computed values match known answers (requires full pipeline)

### Running

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

As of 2026-03-11, this repo and its calibration tests are being rebuilt.
The spec in `spec/` contains the shared understanding of what each detector
measures, what each injection does, and whether they align.

### What works at Gate 1

| Detector | Status | Notes |
|---|---|---|
| outlier_rate | Detects its injection | 5% at 10x multiplier → score ~0.40 |
| benford | Detects its injection | 60% round numbers → score ~0.85 |
| null_ratio | Score too low for threshold | 15% injection → score 0.15, below 0.3 threshold |
| join_path_determinism | No injection in medium strategy | Detector logic is sound |
| type_fidelity | Injection misaligned | 3% corruption doesn't affect type inference (correct behavior) |
| unit_entropy | Injection misaligned | Detector checks metadata presence, not value consistency |
| temporal_entropy | Injection misaligned | Typing handles mixed formats; type↔role stays aligned |
| relationship_entropy | Composite dilutes signal | 5% orphans → score ~0.18 (weighted composite too forgiving) |
| business_meaning | Undertested | Injection too mild (abbreviations). Needs garbage names to test confidence penalty |

### Zone 2+ detectors (not yet calibrated)

| Detector | Zone | Blocked by |
|---|---|---|
| temporal_drift | 2 | Needs DRIFT_SUMMARIES (from temporal_slice_analysis) |
| dimensional_entropy | 2 | Needs SLICE_VARIANCE |
| derived_value | 2 | Needs CORRELATION |
| column_quality | 2 | Needs COLUMN_QUALITY_REPORTS |
| dimension_coverage | 2 | Needs ENRICHED_VIEW |

### Missing detectors (injections without a detector)

- `cross_table_consistency` — 2 injections target this (GL↔Invoice, Payment↔Bank mismatch)
- `derived_value_consistency` — 1 injection targets this (trial balance ↔ GL)

### Key findings

- Most Gate 1 "failures" are injection→detector misalignment, not detector bugs
- The medium strategy injection rates are too low for some detectors (null_ratio, type_fidelity)
- `business_meaning` is undertested — injection uses abbreviations that LLMs handle; needs garbage names
- `relationship_entropy` composite needs decomposition or reweighting
- Gate scores are ephemeral (not persisted) — eval needs this fixed
- The fix system infrastructure is complete but lacks MCP exposure

## Backlog

Tracked in `spec/` documents and Linear (DAT-133, DAT-135, DAT-94).

### Priority: Fix existing detectors
- Fix `business_meaning` injection — use garbage names (rrFlp_11_zp00) instead of abbreviations to test confidence penalty
- Add quarantine rate as sub-signal to `type_fidelity` — already logged during typing
- Observe `relationship_entropy` — never fired, needs real-world data before rewriting formula
- `temporal_entropy` unmarked case (0.6) is valuable — keep it, critical for Zone 2 downstream

### Priority: Fix injection→detector alignment
- `corrupt_types` at 3% doesn't trigger `type_fidelity` — either raise rate, or assign to a different detector (quarantine rate)
- `introduce_nulls` at 15% is below 0.3 threshold — raise rate or lower threshold
- `mix_units` targets value consistency but `unit_entropy` checks metadata — misaligned
- `obscure_column_names` uses abbreviations LLMs handle — needs truly meaningless names
- `corrupt_dates` should target type_fidelity (unparseable formats → quarantine), not temporal_entropy
- `break_referential_integrity` at 5% is diluted by composite — either raise rate or decompose detector

### Priority: Pipeline infrastructure for eval
- Persist gate scores (see spec/00 for three options)
- Update fix CLI (exists but outdated)
- MCP `apply_fix` tool
- Zone-aware pipeline runs (run to gate, stop, fix, continue)

### Future: New detectors (only after existing ones are solid)
- `cross_table_consistency` — cross-table amount reconciliation
- Detectors for validation and business_cycles phases (Zone 3)
- Value-level detectors where current ones only check metadata
