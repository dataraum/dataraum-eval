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

cross_table_consistency — needs Zone 3 (VALIDATION analysis). See zone-3 spec.

## Calibration Results (2026-03-16, zone2-detection-v1)

**Zone 2 detection recall: 5/5 pass**

### Injection-testable (score > 0.3)

| Detector | Target | Score | Notes |
|---|---|---|---|
| temporal_drift | bank_transactions.amount | 1.000 | 1.35x shift after mid-year, JS divergence |
| derived_value | journal_lines.net_amount | 0.708 | 10% formula drift, boost curve, scores on debit via formula chain |
| benford (z1 baseline) | bank_transactions.amount | 0.833 | Zone 1 detector still fires at Gate 2 |
| null_ratio (z1 baseline) | journal_lines.cost_center | 0.709 | Zone 1 detector still fires at Gate 2 |
| relationship_entropy (z1 baseline) | payments.invoice_id | 0.447 | Zone 1 detector still fires at Gate 2 |

### Documentation-debt detectors (tested via fix calibration, not injection recall)

| Detector | Target | Clean | Injected | Notes |
|---|---|---|---|---|
| dimensional_entropy | journal_lines | 0.700 | 0.700 | Natural debit/credit mutex, zero injection delta |
| column_quality | journal_lines | 0.300 | 0.420 | LLM grade noise, baseline at threshold |
| dimension_coverage | enriched_payments | 0.000 | 0.200 | 20% FK orphans, below 0.3 threshold |

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

### COALESCE expressions need TRY_CAST for safe fallthrough
Strategy 1b combines multiple date patterns via COALESCE. It converts STRPTIME
to TRY_STRPTIME (NULL on failure), but non-STRPTIME expressions (like epoch
`CAST(col AS BIGINT)`) must also be error-safe. Use `TRY_CAST` for any inner
type conversion so non-matching values return NULL instead of erroring.

### unit_entropy is correctly misaligned
The detector measures whether the pipeline identified and declared units
(metadata completeness). The mix_units injection corrupts values. These are
different things. The detector works — the injection doesn't test it.

### Documentation-debt detectors need fix-loop testing
dimensional_entropy and column_quality measure intrinsic data complexity, not
injected corruption. Clean data scores 0.5-0.7 (dimensional_entropy) and
0.28-0.30 (column_quality) because the patterns are real business rules.
Injection delta is zero (dimensional_entropy) or noise (column_quality).
The calibration test is: document_business_rule fix → score drops.

### derived_value scoring uses boost + formula chain attribution
The correlations dedup prefers sum over difference: `debit = net_amount + credit`
wins over `net_amount = debit - credit`. Injecting drift on net_amount causes the
debit formula to break, so the score appears on `debit`, not the injected column.
The `_find_score` fallback handles this by checking all columns in the table.

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

## Fix Calibration Results (4b)

**Fix system: 8/10 pass, 2 xfail** (all expected)

### Phase 1: accept_finding (config-only, contract overrule)

Scores stay honest (no clamping). Gate passes via contract overrule:
accepted targets are excluded from violation assessment.

| Detector | Target | Pre | Post | Behavior |
|---|---|---|---|---|
| outlier_rate | journal_lines.credit | 1.000 | ~1.000 | score unchanged, ACCEPTED label |
| benford | bank_transactions.amount | 0.803 | ~0.803 | score unchanged, ACCEPTED label |
| null_ratio | journal_lines.cost_center | 0.711 | ~0.711 | score unchanged, ACCEPTED label |
| relationship_entropy | payments.invoice_id | 0.447 | ~0.447 | score unchanged, ACCEPTED label |

### Phase 2: metadata fixes (direct DB update, re-measure at gate)

| Detector | Target | Pre | Post | Expected |
|---|---|---|---|---|
| business_meaning | invoices.rrflp_11_zp00 | 0.375 | 0.000 | <= 0.1 |
| business_meaning | invoices.xq_v7kl | 0.350 | 0.000 | <= 0.1 |

### Phase 3: config fixes requiring phase re-run

| Detector | Target | Action | Pre | Post | Expected |
|---|---|---|---|---|---|
| temporal_entropy | payments.date | add_type_pattern | 0.800 | ~0 | <= 0.2 |
| type_fidelity | journal_lines.debit | set_column_type | 0.585 | 0.100 | <= 0.1 |

### xfail (fix action doesn't address root cause)

| Detector | Target | Action | Why |
|---|---|---|---|
| temporal_entropy | payments.date | set_timestamp_role | Column already marked as timestamp; the issue is type mismatch (VARCHAR from corrupt dates). add_type_pattern (Phase 3) is the real fix. |
| relationship_entropy | payments.invoice_id | confirm_relationship | ri_entropy (0.447 from 20% orphans) dominates via max aggregation; confirm_relationship only reduces semantic component. accept_finding (Phase 1) is the working fix path. |

### Fix system architecture

The calibration runner supports three fix phases:

**Phase 1+2 (gate-only):** Config/metadata fixes that only need gate
re-measurement. Applies fixes then calls `measure_at_gate()` directly.

**Phase 3 (phase re-run):** Config fixes to typing.yaml or relationships.yaml
that require the pipeline to re-run from the affected phase. The runner:

1. Copies output to `-fixed/` directory
2. Cascade-cleans affected phase + all downstream phases
3. Applies config fixes (typing.yaml, thresholds.yaml) before re-run
4. Re-runs pipeline from the cleaned phase through quality_review
5. Applies metadata fixes on the rebuilt DB, then re-measures gate
6. Persists gate results to PhaseLog

Key constraint: config fixes must be applied BEFORE pipeline re-run (typing
needs forced_types/patterns). Metadata fixes must be applied AFTER (cascade
cleanup deletes the rows that metadata fixes target).

## Backlog

### Next: Zone 3 calibration (see spec/03-zone-3-interpretation.md)
- Implement `cross_table_consistency` detector (consumes ValidationResultRecord)
- Implement `business_cycle_health` detector (consumes DetectedBusinessCycle)
- Add `AnalysisKey.VALIDATION` and `AnalysisKey.BUSINESS_CYCLES`
- Add `computation_review` gate phase (Gate 3)
- Update network.yaml with new nodes + edges
- Create zone3-detection-v1 strategy
- Calibrate cross_table_consistency (injection recall)
- Observe business_cycle_health (documentation-debt style)
- Quick check: Bayesian network + entropy_interpretation
- Ground truth metric verification (graph_execution vs ground_truth.yaml)

### Deferred
- unit_entropy: measures metadata completeness, not value consistency — accept misalignment or create separate injection
- DAT-144: entropy_interpretation may produce novel fix actions not in detector schemas
- Push `measure_at_gate` re-measurement logic into dataraum-context for MCP exposure
- Zone 2 fix schemas: wire FixSchemas for dimensional_entropy, temporal_drift, etc.
- dimension_coverage: add sqrt boost (bundled with Zone 3 work, Step 0 in spec/03)
