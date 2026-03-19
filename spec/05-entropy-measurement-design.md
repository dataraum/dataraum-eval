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

Pipeline configuration is split between YAML (phase list, orchestrator settings)
and Python (dependencies, produces_analyses, is_quality_gate — all class properties).
The YAML is just a phase list. Everything structural lives in code.

## Pipeline YAML: The Standard Interface

Move all structural declarations into `pipeline.yaml`. The scheduler reads one
file and knows: what runs, in what order, what it produces, what entropy it
measures, where the gates are.

```yaml
# Pipeline Configuration
version: "2.0.0"

phases:
  # =========================================================================
  # Zone 1: Foundation
  # =========================================================================
  import:
    description: Load source data into raw tables
    dependencies: []

  typing:
    description: Type inference and resolution
    dependencies: [import]
    produces: [TYPING]
    detectors: [type_fidelity]

  statistics:
    description: Statistical profiling of typed tables
    dependencies: [typing]
    produces: [STATISTICS]
    detectors: [null_ratio, outlier_rate, benford]

  column_eligibility:
    description: Column eligibility evaluation
    dependencies: [statistics]

  statistical_quality:
    description: Benford and outlier analysis
    dependencies: [column_eligibility]

  relationships:
    description: Cross-table relationship detection
    dependencies: [column_eligibility]
    produces: [RELATIONSHIPS]
    detectors: [join_path_determinism, relationship_quality]

  temporal:
    description: Temporal pattern and trend analysis
    dependencies: [column_eligibility]

  semantic:
    description: LLM semantic analysis (tier 1 + tier 2)
    dependencies: [relationships]
    produces: [SEMANTIC]
    detectors: [business_meaning, temporal_entropy, unit_entropy]

  quality_review:
    description: Zone 1 quality checkpoint
    dependencies: [semantic, statistical_quality]
    gate: true

  # =========================================================================
  # Zone 2: Enrichment
  # =========================================================================
  enriched_views:
    description: Create enriched views (fact + dimension JOINs)
    dependencies: [quality_review]
    produces: [ENRICHED_VIEW]
    detectors: [dimension_coverage]

  slicing:
    description: LLM-powered slice dimension identification
    dependencies: [enriched_views]

  slicing_view:
    description: Create slicing views with slice-relevant columns
    dependencies: [slicing]

  slice_analysis:
    description: Execute slice SQL, analyze slice tables
    dependencies: [slicing_view]
    produces: [SLICE_VARIANCE]
    detectors: [slice_variance, dimensional_entropy]

  temporal_slice_analysis:
    description: Distribution drift analysis on slices
    dependencies: [slice_analysis, temporal]
    produces: [DRIFT_SUMMARIES]
    detectors: [temporal_drift]

  correlations:
    description: Within-table correlation analysis
    dependencies: [enriched_views]
    produces: [CORRELATION]
    detectors: [derived_value]

  quality_summary:
    description: LLM quality report generation
    dependencies: [slice_analysis, temporal_slice_analysis]
    produces: [COLUMN_QUALITY_REPORTS]
    detectors: [column_quality]

  analysis_review:
    description: Zone 2 quality checkpoint
    dependencies: [correlations, quality_summary, temporal_slice_analysis]
    gate: true

  # =========================================================================
  # Zone 3: Interpretation
  # =========================================================================
  business_cycles:
    description: Expert LLM cycle detection
    dependencies: [analysis_review, semantic, temporal, enriched_views, slicing, quality_summary]
    produces: [BUSINESS_CYCLES]
    detectors: [business_cycle_health]

  validation:
    description: LLM-powered cross-table validation checks
    dependencies: [analysis_review, semantic, relationships, enriched_views, slicing]
    produces: [VALIDATION]
    detectors: [cross_table_consistency]

  computation_review:
    description: Zone 3 quality checkpoint
    dependencies: [business_cycles, validation]
    gate: true

  entropy_interpretation:
    description: LLM interpretation of entropy (narratives + resolution actions)
    dependencies: [computation_review]

  graph_execution:
    description: Execute metric graphs (LLM-generated SQL)
    dependencies: [entropy_interpretation]

# Limits
limits:
  max_columns: 500

# Pipeline orchestrator settings
pipeline:
  max_parallel: 4
  fail_fast: true
  skip_completed: true

  retry:
    max_retries: 2
    backoff_base: 2.0

# Business pattern filter (spec/04)
pattern_filter:
  enabled: true
  model: haiku
  confidence_threshold: 0.8
  # Only filter findings with score above this minimum
  min_score: 0.1
```

### What moves from Python to YAML

| Property | Currently | Moves to |
|---|---|---|
| `dependencies` | `BasePhase.dependencies` property | `phases.<name>.dependencies` |
| `produces_analyses` | `BasePhase.produces_analyses` property | `phases.<name>.produces` |
| `is_quality_gate` | `BasePhase.is_quality_gate` property | `phases.<name>.gate: true` |
| detector attachment | `required_analyses` on detector class | `phases.<name>.detectors` |
| `description` | `BasePhase.description` property | `phases.<name>.description` |

### What stays in Python

- Phase `_run()` logic — the actual work
- Phase `cleanup()` — cascade deletion
- Phase `should_skip()` — skip conditions
- Phase `db_models` — SQLAlchemy model registration
- Detector `detect()` logic — the actual measurement
- Detector `load_data()` — data loading for the detector
- Detector `scope` — column, table, or view
- Detector scoring, evidence, resolution options

The YAML defines the DAG and the contracts. Python defines the behavior.

### Phase class simplification

Phase classes become simpler — they only need `name` and `_run()`:

```python
@analysis_phase
class TypingPhase(BasePhase):
    @property
    def name(self) -> str:
        return "typing"

    def _run(self, ctx: PhaseContext) -> PhaseResult:
        # ... actual typing logic ...
```

No more `dependencies`, `produces_analyses`, `description`, `is_quality_gate`
properties. The scheduler reads these from YAML and injects them into the phase
instance at registration time.

## Proposed Design

### Principle: Detectors run once, when their input data is ready

Each detector is attached to a phase in YAML (`detectors: [...]`). When that
phase completes, its detectors run as a post-step. The detector persists its
score as an EntropyObjectRecord. Once.

If a phase has `detectors: [null_ratio, outlier_rate, benford]`, all three run
(potentially in parallel) after the phase's `_run()` succeeds. Their records
are persisted in the same transaction.

### Principle: Business pattern filter runs per detector, at measurement time

When a detector produces `score > 0`, the business pattern filter runs immediately:
one Haiku call with the column's semantic context. The filter annotates the
EntropyObject with `expected_business_pattern` before it's persisted. The score
and the annotation are written together — one record, one truth.

The filter only runs if `pattern_filter.enabled: true` in pipeline.yaml and
semantic annotations exist (i.e., semantic phase has completed).

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
1. Read persisted EntropyObjectRecords (already written by preceding phases)
2. Call `compute_network()` to get the current network state
3. Evaluate contracts against scores
4. Respect `expected_business_pattern` annotations (exclude from violations)
5. Persist the gate result to PhaseLog (scores, violations, actions)

No `measure_at_gate()`. No re-running detectors. Just aggregation of what's
already been measured.

## Scheduler Changes

The scheduler currently:
1. Reads `pipeline.yaml` for the phase list
2. Instantiates phase classes, reads their Python properties for dependencies
3. Builds a dependency DAG
4. Executes phases in topological order (parallel where possible)
5. At gates: calls `measure_at_gate()` to run detectors

New scheduler:
1. Reads `pipeline.yaml` for everything: phases, dependencies, produces, detectors, gates
2. Instantiates phase classes (matched by `name`)
3. Builds a dependency DAG from YAML
4. Executes phases in topological order
5. After each phase with `detectors`: runs listed detectors, applies pattern filter, persists
6. At gates (`gate: true`): aggregates persisted records, evaluates contracts

### Detector execution flow

```
Phase._run() succeeds
  → scheduler reads phase.detectors from YAML
  → for each detector_id:
      → instantiate detector
      → detector.load_data(context)
      → objects = detector.detect(context)
      → for each object with score > 0:
          → if pattern_filter.enabled AND semantic annotations exist:
              → verdict = pattern_filter.classify(object, semantic_context)
              → object.expected_business_pattern = verdict.expected
              → object.business_rule = verdict.business_rule
              → object.filter_confidence = verdict.confidence
      → persist all EntropyObjectRecords
```

## What Happens to Existing Phases

### Entropy phase → removed

Detectors run as post-steps of their input phases. The entropy phase has no
remaining purpose. `compute_network()` is callable on-demand.

The entropy phase currently also wipes all existing records at start (clean slate).
In the new design, each detector wipes its own prior records before re-running
(scoped by source_id + detector_id). This is more surgical and supports
incremental re-runs after fixes.

### entropy_interpretation — simplified

Still runs LLM interpretation on entropy data. But it no longer needs
`_run_quality_dependent_detectors` — those detectors already ran as post-steps
of quality_summary and slice_analysis. It just reads persisted records and
calls `compute_network()`.

### quality_summary — gets entropy context naturally

Currently quality_summary depends on the entropy phase for network readiness
filtering. In the new design, by the time quality_summary runs, the Zone 1
detectors have already produced their scores (they ran after typing, statistics,
semantic, relationships). `compute_network()` returns the Zone 1 picture.
quality_summary's network filter works without a dedicated entropy phase.

Note: quality_summary currently depends on `[slice_analysis, temporal_slice_analysis,
entropy]`. The entropy dependency drops. Its detectors (`column_quality`) run
after quality_summary completes, not before.

## Migration Path

### Phase 1: YAML-driven DAG (no detector changes)
- Move dependencies, produces, gate, description to YAML
- Scheduler reads from YAML instead of Python properties
- Phase classes keep properties for backward compat (deprecated, YAML wins)
- No functional change — same execution order, same results

### Phase 2: Detectors as post-steps
- Scheduler runs detectors listed in `phases.<name>.detectors` after phase completes
- Remove entropy phase
- Remove `_run_quality_dependent_detectors` from entropy_interpretation
- Remove `measure_at_gate()` — gates read persisted records
- Update fix system's `apply_fixes` to read records instead of re-measuring

### Phase 3: Business pattern filter
- Add pattern_filter config to YAML
- Implement Haiku classification (spec/04)
- Wire into post-step detector execution
- Update gates to respect `expected_business_pattern` annotations

## Open Questions

- **Incremental vs clean-slate.** If typing re-runs (after a fix), do we wipe
  only type_fidelity's records and re-run it? The cascade cleanup already knows
  which phases to reset — detector cleanup follows the same cascade.

- **Filter cost on re-runs.** Each re-run costs ~20-40 Haiku calls. Acceptable
  for fix loops (1-3 iterations). Cache by (column, detector, pattern_hash).

- **YAML validation.** The YAML becomes critical infrastructure. Need schema
  validation: all detector_ids must exist in the registry, all phase names must
  have a matching Python class, dependency cycles are rejected at load time.

- **Per-phase config files.** Phase-specific config currently lives in
  `config/phases/<name>.yaml`. These stay — they hold runtime parameters
  (batch sizes, thresholds). The pipeline YAML holds structural declarations.

- **Backward compatibility.** Python properties on phase classes become
  deprecated. They can coexist during migration (YAML wins if present,
  fall back to Python property). Remove after migration is complete.
