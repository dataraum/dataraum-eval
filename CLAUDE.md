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
make calibrate                         # detection-v1 (comprehensive)
make calibrate-typing                  # detection-typing-v1 (type-breaking only)

# Or step by step:
make generate-detection-v1             # testdata → data/detection-v1/
make pipeline-detection-v1             # pipeline → output/detection-v1/
uv run pytest calibration/ --strategy detection-v1 -v

# Clean everything
make clean
```

The runner (`calibration/runner.py`) calls `testdata.scenarios.runner.run_scenario`
and `dataraum.pipeline.runner.run` directly. Strategy YAML files in `strategies/`
control injection parameters and detector_id overrides.

## How Calibration Works

1. **Strategy YAML** defines injections with known parameters (rate, target column,
   detector_id override)
2. **testdata** generates clean financial data, applies injections, writes
   `entropy_map.yaml` listing exactly what was injected
3. **Pipeline** runs all phases, post-step detectors write `EntropyObjectRecord` rows
4. **conftest.py** calls `measure_entropy()` to aggregate detector records into
   `(table, column, detector_id) → score`
5. **test_detector_recall.py** asserts each injection's detector scores above
   `DETECTION_THRESHOLD` (0.3) for the affected column

## What We Test

### 4a: Detection calibration (current focus)
Inject → run pipeline → measure entropy → assert thresholds.
Pure data, no LLM involvement in the test loop (LLM runs during pipeline's
semantic phase, but tests only check scores).

### 4b: Fix calibration
Detector fires → agent proposes fix → fix applied → score drops.
LLM-in-the-loop. Requires MCP `apply_fix` tool.

## Strategy Design

Two strategies, split by data source type:

### detection-v1 (comprehensive)

All detectors except type-breaking. No `corrupt_types` or `corrupt_dates`
injections, so all columns retain proper types. This allows temporal, dimensional,
cross-table, and derived-value detectors to work without interference.

14 injections covering: null_ratio, outlier_rate, benford, temporal_drift,
unit_entropy, business_meaning, relationship_entropy, dimensional_entropy,
derived_value, cross_table_consistency (3 validations), slice_variance.

### detection-typing-v1 (type-breaking)

Type-breaking injections only: `corrupt_types` (journal_lines.debit) +
`corrupt_dates` (payments.date). Only relevant for text-based sources
(CSV, Excel, SQLite) where the pipeline must infer types.

Tests: type_fidelity, temporal_entropy.

### Strategy parameters

- `detector_id`: override which detector this injection targets (used in
  entropy_map.yaml for test assertions)
- `ratio`: injection rate — must be high enough for the detector's scoring
  curve to cross threshold
- `formats` (corrupt_dates): must use injector's dispatch names, not strftime

## Detection Calibration Results (2026-03-24, detection-v1)

**Detection recall: 12/14 pass, 2 xfail**

### Passing (score > 0.3)

| Detector | Target | Score | Notes |
|---|---|---|---|
| null_ratio | journal_lines.cost_center | ~0.71 | 40% injection rate |
| outlier_rate | journal_lines.credit | 1.000 | 5% at 10x multiplier |
| benford | bank_transactions.amount | ~0.80 | 60% round numbers |
| temporal_drift | bank_transactions.amount | 1.000 | 1.35x shift after mid-year |
| business_meaning | invoices.rrflp_11_zp00 | ~0.38 | LLM confidence on garbage name |
| business_meaning | invoices.xq_v7kl | ~0.35 | LLM confidence on garbage name |
| relationship_entropy | payments.invoice_id | ~0.45 | sqrt-boosted 20% orphan rate |
| dimensional_entropy | journal_lines.debit/credit | ~0.70 | Natural debit/credit mutex |
| derived_value | journal_lines.net_amount | ~0.71 | 10% formula drift, boost curve |
| cross_table (gl_invoice) | invoices.amount | pass | 15% amount corruption, FK join |
| cross_table (payment_bank) | payments.amount | pass | 15% amount corruption, FK join |
| cross_table (trial_balance) | trial_balance.credit_balance | pass | 10% balance corruption |

### Known misaligned (xfail)

| Detector | Target | Root cause |
|---|---|---|
| unit_entropy | invoices.amount | Measures metadata completeness, not value consistency. Injection targets values |
| derived_value | trial_balance.debit_balance | Cross-table aggregate (TB vs GL), not within-table formula. Out of scope for derived_value |

### Detection-typing-v1 results (type-breaking)

| Detector | Target | Score | Notes |
|---|---|---|---|
| type_fidelity | journal_lines.debit | 0.585 | Boost function on 8% quarantine rate |
| temporal_entropy | payments.date | 0.800 | Corrupt dates → VARCHAR → type/role mismatch |

## Fix Calibration Results (4b)

**Fix system: 8/10 pass, 2 xfail** (all expected)

### Phase 1: accept_finding (config-only, contract overrule)

Scores stay honest (no clamping). Contract passes via overrule:
accepted targets are excluded from violation assessment.

| Detector | Target | Pre | Post | Behavior |
|---|---|---|---|---|
| outlier_rate | journal_lines.credit | 1.000 | ~1.000 | score unchanged, ACCEPTED label |
| benford | bank_transactions.amount | 0.803 | ~0.803 | score unchanged, ACCEPTED label |
| null_ratio | journal_lines.cost_center | 0.711 | ~0.711 | score unchanged, ACCEPTED label |
| relationship_entropy | payments.invoice_id | 0.447 | ~0.447 | score unchanged, ACCEPTED label |

### Phase 2: metadata fixes (direct DB update, re-measure)

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

**Phase 1+2 (measurement-only):** Config/metadata fixes that only need
re-measurement. Applies fixes then calls `measure_entropy()` directly.

**Phase 3 (phase re-run):** Config fixes to typing.yaml or relationships.yaml
that require the pipeline to re-run from the affected phase. The runner:

1. Copies output to `-fixed/` directory
2. Cascade-cleans affected phase + all downstream phases
3. Applies config fixes (typing.yaml, thresholds.yaml) before re-run
4. Re-runs pipeline from the cleaned phase
5. Applies metadata fixes on the rebuilt DB, then re-measures
6. Scores read via `measure_entropy()` (no longer persisted to PhaseLog)

Key constraint: config fixes must be applied BEFORE pipeline re-run (typing
needs forced_types/patterns). Metadata fixes must be applied AFTER (cascade
cleanup deletes the rows that metadata fixes target).

## Key Learnings

### Detector scoring needs non-linear amplification
Linear `score = rate` under-weights real problems. 8% quarantine means 8% of
your data is broken — that's not 0.08 severity. The `_boost_rate()` function
in type_fidelity uses `((1+rate)^2/-log10(rate))-0.5` to map small rates to
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

### Documentation-debt detectors need fix-loop testing
dimensional_entropy measures intrinsic data complexity, not injected corruption.
Clean data scores 0.5-0.7 because the patterns are real business rules.
Injection delta is zero. The calibration test is: document_business_rule fix → score drops.

### derived_value scoring uses boost + formula chain attribution
The correlations dedup prefers sum over difference: `debit = net_amount + credit`
wins over `net_amount = debit - credit`. Injecting drift on net_amount causes the
debit formula to break, so the score appears on `debit`, not the injected column.
The `_find_score` fallback handles this by checking all columns in the table.

### Cross-table validations need explicit FK join paths
LLM agents fall back to fuzzy date+amount matching when FK paths aren't obvious,
masking corruption. Testdata must include explicit FK columns (e.g., Invoice.entry_id,
BankTransaction.payment_id) and validation specs must mandate FK-first join strategy.

### Aggregate evaluator must check rates against tolerance
The validation agent's aggregate handler was returning `passed=True` unconditionally.
Must extract orphan_rate/violation_rate from results and compare against the
tolerance parameter. Otherwise cross-table validations never fail.

## Backlog

### Calibration improvements
- Update network.yaml with cross_table and business_cycle nodes + edges
- Wire fix schemas for dimensional_entropy, temporal_drift, etc.
- dimension_coverage: add sqrt boost
- unit_entropy: accept misalignment or create separate injection

### Roadmap (see [Pipeline Redesign](https://linear.app/dataraum/project/pipeline-redesign-yaml-driven-dag-entropy-measurement-9c6b0d33aa5c))
- Business pattern filter — LLM classification to distinguish expected patterns from real issues
- Pipeline YAML redesign — single source of truth, post-step declarations
- Showcase playbooks — real-world test scenarios for demo
