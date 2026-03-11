# Zone 2: Enrichment — Outline

> Zone 2 runs from enriched views through quality summary. It ends at a
> proposed `analysis_review` gate (DAT-109). This zone joins data across
> tables, detects cross-column patterns, and measures drift.
>
> This document is intentionally thin. Zone 2 calibration follows Zone 1.
> Do not invest in Zone 2 detector calibration until Zone 1 detectors are solid.

## Phases

```
enriched_views (LLM — creates fact+dim JOINs)
  → correlations (detects derived columns/formulas)
  → slicing (LLM — selects categorical dimensions)
  → slicing_view (creates DuckDB slice tables)
  → slice_analysis (profiles slices, produces SLICE_VARIANCE)
  → temporal_slice_analysis (period-over-period drift, produces DRIFT_SUMMARIES)
  → quality_summary (LLM — grades column quality across slices, produces COLUMN_QUALITY_REPORTS)
  → analysis_review [GATE 2 — proposed]
```

## Additional Analyses at Gate 2

| AnalysisKey | Phase | What it contains |
|---|---|---|
| ENRICHED_VIEW | enriched_views | Grain-preserving JOINs, dimension column metadata |
| CORRELATION | correlations | DerivedColumn records: formulas, match rates, source columns |
| SLICE_VARIANCE | slice_analysis | Per-slice statistical profiles, variance across categories |
| DRIFT_SUMMARIES | temporal_slice_analysis | ColumnDriftSummary: JS divergence per period, drift evidence |
| COLUMN_QUALITY_REPORTS | quality_summary | ColumnQualityReport: LLM quality grades per column per slice |

## Additional Detectors at Gate 2

| Detector | Measures | Scope | Required analyses |
|---|---|---|---|
| temporal_drift | Period-over-period distribution shift (JS divergence) | column | DRIFT_SUMMARIES, SEMANTIC |
| dimensional_entropy | Undocumented cross-column patterns (mutual exclusivity, correlations) | table | SLICE_VARIANCE |
| column_quality | LLM quality grades inverted to entropy | table | COLUMN_QUALITY_REPORTS |
| dimension_coverage | NULL rate in enriched view dimension columns | view | ENRICHED_VIEW |
| derived_value | Formula match rate from correlation analysis | column | CORRELATION |

## Injections Detectable at Gate 2

| Injection | Detector | Expected outcome |
|---|---|---|
| inject_temporal_drift (1.35x after cutoff) | temporal_drift | Should detect — 35% shift causes high JS divergence |
| create_mutual_exclusivity (debit/credit XOR) | dimensional_entropy | Should detect — mutual exclusivity pattern |
| drift_formula (2% errors) | derived_value | Uncertain — 2% error rate may be too subtle (score ≈ 0.02) |

## Fix Schemas at Gate 2

Inherits all Zone 1 config fixes. Additionally:
- `dimensional_entropy` → `create_constraint` (metadata target → SemanticAnnotation)
- `dimensional_entropy` → `document_business_rule` (config target → semantic.yaml)

## Open Items (Deferred)

- Gate 2 phase (`analysis_review`) does not exist yet — DAT-109
- Should `derived_value` have fix schemas?
- Should `temporal_drift` have fix schemas? (Currently none declared)
- What injection rate is needed for `drift_formula` to reliably trigger `derived_value`?
- Cross-column correlation detection: does the correlations phase detect
  enough for the derived_value detector to work on cross-table formulas?
