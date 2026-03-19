# Entropy Measurement Redesign

> Where and when entropy is measured, filtered, persisted, and consumed.
> Companion to `04-business-pattern-filter.md`.

## Current State (problems)

Entropy is measured redundantly:

1. **Gate measurement** (`measure_at_gate`) — runs detectors fresh, scores go to
   PhaseLog. Ephemeral. Repeated at every gate.
2. **Entropy phase** — runs detectors again, persists EntropyObjectRecords.
   Redundant with gate measurement.
3. **entropy_interpretation** — runs quality-dependent detectors a third time
   (`_run_quality_dependent_detectors`). Needed because some detectors couldn't
   run during the entropy phase (their input data didn't exist yet).

The same detector can execute 3-4 times with slightly different results.
Measurement is scattered. No single source of truth.

## Proposed Design

### Principle: Detectors run once, when their input data is ready

Each detector declares `required_analyses` — the analyses it needs. When the last
required analysis completes (the phase that produces it finishes), the detector runs
and persists its score. Once. The score is an EntropyObjectRecord in metadata.db.

This is already how `required_analyses` + `produces_analyses` work conceptually.
The change: instead of batching all detectors into an "entropy phase," detectors
run as a post-step of the phase that completes their requirements.

### Principle: Business pattern filter runs per detector, at measurement time

When a detector produces `score > 0`, the business pattern filter runs immediately:
one Haiku call with the column's semantic context. The filter annotates the
EntropyObject with `expected_business_pattern` before it's persisted. The score
and the annotation are written together — one record, one truth.

### Principle: The entropy network is a pure function over persisted records

`compute_network(session, source_id) → EntropyForNetwork` already exists. It reads
all EntropyObjectRecords for a source and builds the Bayesian network. Call it
anytime — during a gate, in get_context, in entropy_interpretation. It always
returns the current picture based on whatever records exist.

The network doesn't need the business pattern filter. It operates on raw scores.
The filter annotations are metadata for gates and agents — the network models
interdependencies regardless of whether a pattern is "expected."

### Principle: Gates are ephemeral aggregation, not measurement

Gates don't run detectors. They:
1. Read persisted EntropyObjectRecords (already written by phases)
2. Call `compute_network()` to get the current network state
3. Evaluate contracts against scores
4. Respect `expected_business_pattern` annotations (exclude from violations)
5. Persist the gate result to PhaseLog (scores, violations, actions)

No `measure_at_gate()`. No re-running detectors. Just aggregation of what's
already been measured.

## When Each Detector Runs

The detector runs as a post-step of the phase that completes its last
required analysis. Using existing `required_analyses` declarations:

| Detector | required_analyses | Runs after phase |
|---|---|---|
| type_fidelity | TYPING | typing |
| null_ratio | STATISTICS | statistics |
| outlier_rate | STATISTICS | statistics |
| benford | STATISTICS | statistics |
| business_meaning | SEMANTIC | semantic |
| temporal_entropy | SEMANTIC | semantic |
| unit_entropy | SEMANTIC | semantic |
| join_path_determinism | RELATIONSHIPS | relationships |
| relationship_quality | RELATIONSHIPS | relationships |
| temporal_drift | DRIFT_SUMMARIES | temporal_slice_analysis |
| derived_value | CORRELATION | correlations |
| slice_variance | SLICE_VARIANCE | slice_analysis |
| column_quality | COLUMN_QUALITY_REPORTS | quality_summary |
| dimensional_entropy | SLICE_VARIANCE | slice_analysis |
| dimension_coverage | ENRICHED_VIEW | enriched_views |
| cross_table_consistency | VALIDATION | validation |
| business_cycle_health | BUSINESS_CYCLES | business_cycles |

Some detectors need multiple analyses (e.g., dimensional_entropy needs
SLICE_VARIANCE + optionally temporal data). They run when ALL required
analyses are available — i.e., after the last required phase completes.

## What Happens to Existing Phases

### Entropy phase → Network phase (or removed)

Currently the entropy phase runs all detectors. In the new design, detectors
run as post-steps of their input phases. The entropy phase becomes either:

- **A network computation phase** — calls `compute_network()`, persists the
  network snapshot for downstream consumers. No detector execution.
- **Removed entirely** — `compute_network()` is callable on-demand.
  entropy_interpretation and gates call it when they need it. No dedicated phase.

### entropy_interpretation — unchanged conceptually

Still runs LLM interpretation on entropy data. But it no longer needs
`_run_quality_dependent_detectors` — those detectors already ran as post-steps
of quality_summary and slice_analysis.

### quality_summary — gets entropy context naturally

Currently quality_summary depends on the entropy phase for network readiness
filtering. In the new design, by the time quality_summary runs, the Zone 1
detectors have already produced their scores (they ran after typing, statistics,
semantic, relationships). The network function returns the Zone 1 picture.
quality_summary's network filter works without a dedicated entropy phase.

## Business Pattern Filter Integration

The filter is NOT a phase. It's a function called inline when a detector
produces a score > 0:

```
Phase completes → detector runs → score > 0? → pattern filter (Haiku) → annotated record persisted
```

The filter has access to:
- The detector's finding (score, evidence, pattern description)
- Semantic annotations for the column (already in metadata.db)
- Table entity description and grain (already in metadata.db)
- Relationship context (already in metadata.db)

No additional data loading needed — everything is already persisted by prior phases.

### Filter placement per zone

| Zone | Detectors that run | Filter available? |
|---|---|---|
| Zone 1 (after typing through semantic) | type_fidelity, null_ratio, outlier_rate, benford, business_meaning, temporal_entropy, unit_entropy, relationship_quality, join_path_determinism | Yes — semantic annotations exist |
| Zone 2 (after enrichment) | temporal_drift, derived_value, slice_variance, dimensional_entropy, column_quality, dimension_coverage | Yes |
| Zone 3 (after validation/cycles) | cross_table_consistency, business_cycle_health | Yes |

The filter is available from Zone 1 onward because semantic annotations (the
primary input) are produced before Gate 1.

## Open Questions

- **Detector as post-step: mechanism.** How does the scheduler know to run
  detectors after a phase? Options: (a) each phase declares which detectors to
  run as a post-step, (b) the scheduler checks all detectors after each phase
  and runs those whose requirements are newly met, (c) detectors register
  themselves with the phases that produce their analyses.

- **Incremental vs clean-slate.** Current entropy phase wipes all records before
  re-running. In the new design, if typing re-runs (after a fix), do we wipe
  only type_fidelity's records and re-run it? This is more surgical but needs
  careful cascade tracking.

- **Filter cost on re-runs.** If a phase re-runs after a fix, its detectors
  re-run, the filter re-runs. Each re-run costs ~20-40 Haiku calls. Acceptable
  for fix loops (usually 1-3 iterations) but could add up. Caching by
  (column, detector, pattern_hash) would help.

- **Network snapshot persistence.** If the entropy phase becomes a network phase,
  it persists a snapshot. But the network changes every time a new detector runs.
  Do we re-compute after each detector, or batch at gates? On-demand (via function)
  is simplest — no persistence needed, just compute when asked.

- **Backward compatibility.** `measure_at_gate()` is used by the fix system's
  `apply_fixes` API and the calibration runner's `measure_at_gate()` calls.
  These would need to switch to reading persisted records + calling
  `compute_network()`. Phase-by-phase migration possible.
