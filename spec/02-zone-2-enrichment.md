# Zone 2: Enrichment

> Zone 2 runs from enriched views through temporal slice analysis. This zone
> joins data across tables, detects cross-column patterns, and measures drift.

## Phases

```
enriched_views (LLM — creates fact+dim JOINs)
  → correlations (detects derived columns/formulas)
  → slicing (LLM — selects categorical dimensions)
  → slicing_view (creates DuckDB slice views)
  → slice_analysis (profiles slices, produces SLICE_VARIANCE)
  → temporal_slice_analysis (period-over-period drift, produces DRIFT_SUMMARIES)
```

## Zone 2 Analyses

| AnalysisKey | Phase | What it contains |
|---|---|---|
| ENRICHED_VIEW | enriched_views | Grain-preserving JOINs, dimension column metadata |
| CORRELATION | correlations | DerivedColumn records: formulas, match rates, source columns |
| SLICE_VARIANCE | slice_analysis | Per-slice statistical profiles, variance across categories |
| DRIFT_SUMMARIES | temporal_slice_analysis | ColumnDriftSummary: JS divergence per period, drift evidence |
## Zone 2 Detectors

| Detector | Measures | Scope | Required analyses | Injection-testable? |
|---|---|---|---|---|
| temporal_drift | Period-over-period distribution shift (JS divergence) | column | DRIFT_SUMMARIES, SEMANTIC | Yes |
| dimensional_entropy | Undocumented cross-column patterns (mutual exclusivity, correlations) | table | SLICE_VARIANCE | No — measures documentation debt |
| dimension_coverage | NULL rate in enriched view dimension columns | view | ENRICHED_VIEW | Yes (via FK orphans) |
| derived_value | Formula match rate from correlation analysis | column | CORRELATION | Yes |

### Detector Categories

**Injection-testable** (recall test: inject → score rises above threshold):
- `temporal_drift`: inject_temporal_drift creates a distribution shift detectable via JS divergence
- `dimension_coverage`: break_referential_integrity creates orphan FKs → NULL dimension columns in enriched views
- `derived_value`: drift_formula corrupts a derived column → match_rate drops → boosted score rises

**Documentation-debt detectors** (fix test: document rule → score drops):
- `dimensional_entropy`: Detects undocumented cross-column patterns (e.g. debit/credit mutual exclusivity). Clean data already scores 0.5-0.7 because the patterns are real business rules. The test is: `document_business_rule` fix → score drops.

## Calibration Results (zone2-detection-v1)

### Detection Recall

| Detector | Target | Score | Status |
|---|---|---|---|
| temporal_drift | bank_transactions.amount | 1.000 | PASS |
| derived_value | journal_lines.net_amount | 0.708 | PASS (scores on debit via formula chain) |
| benford (z1 baseline) | bank_transactions.amount | 0.833 | PASS |
| null_ratio (z1 baseline) | journal_lines.cost_center | 0.709 | PASS |
| relationship_entropy (z1 baseline) | payments.invoice_id | 0.447 | PASS |

### Baseline Scores (documentation-debt detectors)

| Detector | Target | Clean | Injected | Notes |
|---|---|---|---|---|
| dimensional_entropy | journal_lines | 0.700 | 0.700 | Natural debit/credit mutex |
| dimensional_entropy | trial_balance | 0.500 | 0.500 | Natural balance patterns |
| dimension_coverage | enriched_payments | 0.000 | 0.200 | 20% FK orphans |

### Scoring Curves

**derived_value** uses non-linear boost (same as type_fidelity):
```
mismatch 0.01 → score 0.01 (noise)
mismatch 0.05 → score 0.35 (fires threshold)
mismatch 0.10 → score 0.56 (clearly broken)
mismatch 0.15 → score 1.00 (severe)
```

## Injections in zone2-detection-v1

| Injection | Detector | Params | Notes |
|---|---|---|---|
| inject_temporal_drift | temporal_drift | 1.35x shift after 2025-07-01 | Column-scoped, high signal |
| drift_formula | derived_value | 10% error in net_amount = debit - credit | Requires correlations to detect formula first |
| break_benford | benford | 60% round numbers | Zone 1 baseline check at Zone 2 |
| introduce_nulls | null_ratio | 40% on cost_center | Zone 1 baseline check at Zone 2 |
| break_referential_integrity | relationship_entropy | 20% orphans on invoice_id | Also creates dimension_coverage signal (0.2) |

### Removed Injections

- `create_mutual_exclusivity` (debit/credit): Removed — clean data already has natural mutual exclusivity (score 0.7). Injection added zero delta.

## Fix Schemas (Zone 2)

Inherits all Zone 1 config fixes. Zone 2-specific fix schemas are not yet implemented (4b scope). Planned:

- `dimensional_entropy` → `create_constraint` (metadata target → SemanticAnnotation)
- `dimensional_entropy` → `document_business_rule` (config target → semantic.yaml)
- `temporal_drift` → `investigate_drift`, `transform_add_time_filter` (resolution hints exist, no FixSchema yet)
- `dimension_coverage` → `investigate_relationship` (resolution hint, no FixSchema yet)
- `derived_value` → `document_formula`, `investigate_formula_mismatches` (resolution hints, no FixSchema yet)

## Injections NOT Detectable at Any Zone

| Injection | Assigned detector | Why it's undetectable |
|---|---|---|
| mix_units (10%, ×1.1) | unit_entropy | **Unit_entropy measures metadata** (is a unit declared?), not value consistency. The injection multiplies 10% of `invoices.amount` by 1.1 while leaving `currency=USD` unchanged. Since all rows share one currency value, slicing by currency produces one group — there's nothing to compare across slices. The 10% × 1.1 shift is too subtle for outlier/Benford detection on the full column. Detection would require either cross-table reconciliation (compare with GL amounts) or sub-population detection within a single currency group — neither exists. The `break_gl_invoice_match` injection already tests cross-table consistency separately. |

## Key Learnings

### Documentation-debt detectors need fix-loop testing, not injection recall
dimensional_entropy measures intrinsic data complexity. Clean data scores high because the patterns are real business rules. The calibration test is: apply `document_business_rule` fix → score drops, not inject → score rises.

### derived_value needs non-linear scoring
Linear `score = 1 - match_rate` requires 30%+ formula errors to cross 0.3 threshold. The boost function (same as type_fidelity) maps 5% errors to score 0.35, matching actual severity: 5% of your derived values being wrong is a real problem.

### Cross-table correlation detection is Zone 3
The correlations phase only detects same-table arithmetic (col1 op col2). Cross-table aggregates (e.g., trial_balance = SUM(journal_lines)) need the validation/business_cycles phases in Zone 3.

## Open Items

- ~~Validate derived_value end-to-end~~ Done: correlations detects `debit = net_amount + credit` (sum preferred over difference), drift_formula corrupts net_amount → match_rate drops → boosted score 0.708
- Zone 2 fix calibration (4b): wire FixSchemas for dimensional_entropy, temporal_drift, etc.
- dimension_coverage: signal is 0.2 from 20% FK orphans — below 0.3 threshold. Either raise orphan rate or accept as sub-threshold (the detector works, the injection is just too mild)
- Ontological entropy detection (mix_units, semantic ambiguity): separate workstream post-zone calibration
