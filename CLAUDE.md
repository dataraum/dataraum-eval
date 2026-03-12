# DataRaum Eval

Calibration harness for the DataRaum entropy detection and fix system.
This repo is a **testing and evaluation framework** — it owns the ground truth
about whether detectors work, and drives changes to detector code and injection
strategies until they do.

## Architecture

Three repos, vendored as git submodules under `vendor/`:

| Repo | Role | Editable from here? |
|------|------|---------------------|
| `dataraum-testdata` | Generates data with known injections (`entropy_map.yaml`) | Yes — `vendor/dataraum-testdata` |
| `dataraum-context` | Pipeline: phases, detectors, fix system | Yes — `vendor/dataraum-context` |
| `dataraum-eval` (this) | Strategies, calibration tests, runner | Yes |

Everything runs from this repo via direct Python API calls — no subprocess
shelling out to sibling repos.

## Running Calibration

```bash
# Full run: generate + pipeline + test
make calibrate-zone1-detection-v1

# Or step by step:
make generate-zone1-detection-v1      # testdata → data/zone1-detection-v1/
make pipeline-zone1-detection-v1      # pipeline → output/zone1-detection-v1/
uv run pytest calibration/ --strategy zone1-detection-v1 -v
```

The runner (`calibration/runner.py`) calls `testdata.scenarios.runner.run_scenario`
and `dataraum.pipeline.runner.run` directly. Strategy YAML files in `strategies/`
control injection parameters and detector_id overrides.

## How Calibration Works

1. **Strategy YAML** defines injections with known parameters (rate, target column,
   detector_id override)
2. **testdata** generates clean financial data, applies injections, writes
   `entropy_map.yaml` listing exactly what was injected
3. **Pipeline** runs through Zone 1 phases to `quality_review` gate, persists
   gate scores in `PhaseLog.outputs["gate_column_details"]`
4. **conftest.py** reads gate scores from `metadata.db` as
   `(table, column, detector_id) → score`
5. **test_detector_recall.py** asserts each injection's detector scores above
   `DETECTION_THRESHOLD` (0.3) for the affected column

## What We Test

### 4a: Detection calibration (current focus)
Inject → run pipeline → read gate scores → assert thresholds.
Pure data, no LLM involvement in the test loop (LLM runs during pipeline's
semantic phase, but tests only check scores).

### 4b: Fix calibration (next)
Detector fires → agent proposes fix → fix applied → score drops.
LLM-in-the-loop. Requires MCP `apply_fix` tool.

## Calibration Results (2026-03-12, zone1-detection-v1)

**Zone 1 detection recall: 8/9 pass** (all except unit_entropy which is misaligned)

### Passing (score > 0.3)

| Detector | Target | Score | Notes |
|---|---|---|---|
| type_fidelity | journal_lines.debit | 0.585 | Boost function on 8% quarantine rate |
| null_ratio | journal_lines.cost_center | 0.711 | 40% injection rate |
| outlier_rate | journal_lines.credit | 1.000 | 5% at 10x multiplier |
| benford | bank_transactions.amount | 0.803 | 60% round numbers |
| business_meaning | invoices.rrflp_11_zp00 | 0.375 | LLM confidence 0.25 on garbage name |
| business_meaning | invoices.xq_v7kl | 0.350 | LLM confidence 0.30 on garbage name |
| temporal_entropy | payments.date | 0.800 | Corrupt dates → VARCHAR → type/role mismatch |
| relationship_entropy | payments.invoice_id | 0.447 | sqrt-boosted 20% orphan rate |

### Known misaligned (xfail)

| Detector | Target | Score | Root cause |
|---|---|---|---|
| unit_entropy | invoices.amount | ~0.1 | Measures metadata completeness, not value consistency. Injection targets values |

### Not testable at Zone 1

temporal_drift, dimensional_entropy, cross_table_consistency,
derived_value, derived_value_consistency — need Zone 2+ analyses.

## Key Learnings

### Detector scoring needs non-linear amplification
Linear `score = rate` under-weights real problems. 8% quarantine means 8% of
your data is broken — that's not 0.08 severity. The `_boost_rate()` function
in type_fidelity uses `((1+rate)²/-log₁₀(rate))-0.5` to map small rates to
scores that match actual severity.

### LLM confidence must be calibrated at both tiers
The business_meaning detector relies on LLM confidence to catch garbage column
names. Without guidance, LLMs report 0.85-0.90 confidence on garbage names
because they infer meaning from data. The fix: add `<confidence_guidance>` to
BOTH tier 1 and tier 2 prompts, update the Pydantic field description, and
tell tier 2 to PRESERVE (not UPGRADE) confidence reflecting name readability.
Tier 2 was the main problem — it "upgraded" low tier-1 confidence to high.

### Weighted average composites hide problems
relationship_entropy's weighted average (0.5 RI + 0.3 cardinality + 0.2 semantic)
made 20% orphan rates invisible. Max aggregation with sqrt-boosted RI is direct:
the worst problem drives the score.

### Injector dispatch must match strategy format names
The corrupt_dates injector uses human-readable format names (`DD/MM/YYYY`) for
dispatch. The strategy had strftime format strings (`%d/%m/%Y`). Nothing matched
→ fallback to isoformat → zero corruption. **Always verify injector output.**

### unit_entropy is correctly misaligned
The detector measures whether the pipeline identified and declared units
(metadata completeness). The mix_units injection corrupts values. These are
different things. The detector works — the injection doesn't test it.

## Strategy Design

Strategies in `strategies/` control what gets injected. Key parameters:

- `detector_id`: override which detector this injection targets (used in
  entropy_map.yaml for test assertions)
- `ratio`: injection rate — must be high enough for the detector's scoring
  curve to cross threshold
- `formats` (corrupt_dates): must use injector's dispatch names, not strftime

### Current strategy: zone1-detection-v1

Raised rates vs baseline medium strategy:
- null_ratio: 15% → 40% (was below 0.3 threshold)
- corrupt_types: 3% → 15% (was invisible to type inference)
- break_ref_integrity: 5% → 20% (composite diluted signal)
- column names: abbreviations → garbage (`rrFlp_11_zp00`)
- corrupt_dates: formats fixed to use injector dispatch names + epoch

## Backlog

### Next: unit_entropy
- Document that it measures metadata completeness, not value consistency
- Either accept the misalignment or create a separate value-consistency injection

### Next: Fix calibration (4b)
- MCP `apply_fix` tool
- Agent proposes fix → fix applied → score drops
- Tests the full loop, not just detection

### Future
- Zone 2 calibration (temporal_drift, dimensional_entropy, derived_value)
- cross_table_consistency detector (needs JOINs, Zone 2+)
- Clean data baseline (all scores below threshold, no false alarms)
