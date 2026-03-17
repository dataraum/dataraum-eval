# Quality Zones — Overarching Concept

> The pipeline processes data through progressive quality zones. Each zone
> ends at a quality gate where entropy is measured, fixes can be applied,
> and the pipeline re-runs within the zone before advancing.

## Zone Model

```
Zone 1: Foundation          Zone 2: Enrichment           Zone 3: Interpretation
─────────────────────       ─────────────────────        ─────────────────────
import                      enriched_views               business_cycles
typing                      correlations                 validation
statistics                  slicing
column_eligibility          slicing_view                 entropy (Bayesian net)
statistical_quality         slice_analysis               ├── entropy_interpretation [LEAF]
relationships               temporal_slice_analysis      └── graph_execution [LEAF]
temporal                    quality_summary
semantic
                            ┌──────────────────┐        ┌──────────────────────┐
┌──────────────────┐        │  analysis_review  │        │  computation_review   │
│  quality_review   │        │   [GATE 2]        │        │   [GATE 3]            │
│   [GATE 1]        │        └──────────────────┘        └──────────────────────┘
└──────────────────┘
```

## What a Zone Provides

Each zone guarantees a set of completed analyses. Detectors declare which
analyses they need (`required_analyses`). A detector runs at the earliest zone
where all its analyses are available.

| Zone | Analyses available | Detectors runnable |
|---|---|---|
| 1 | TYPING, STATISTICS, SEMANTIC, RELATIONSHIPS | 9 (see zone-1 spec) |
| 2 | + ENRICHED_VIEW, CORRELATION, SLICE_VARIANCE, COLUMN_QUALITY_REPORTS, DRIFT_SUMMARIES | +5 = 14 total |
| 3 | + VALIDATION, BUSINESS_CYCLES + Bayesian network interdependency assessment | +2 (cross_table_consistency, business_cycle_health) = 16 total |

## Zone Gate Mechanics

At each gate, the scheduler:
1. Runs `measure_at_gate()` — invokes all detectors whose analyses are satisfied
2. Runs `assess_contracts()` — compares scores against contract thresholds
3. If violations: yields `EXIT_CHECK` event with scores + available fix schemas
4. Caller resolves: DEFER, ABORT, or FIX
5. If FIX: applies fix via interpreters → resets affected phases → re-runs → re-measures
6. Repeats until no violations or caller defers

## Fix System

Fixes are user/agent decisions, not automatic corrections. The system identifies
the problem (detector), the user makes the judgment (via agent questions), and
the phase knows how to apply the decision (fix handler).

**Three fix targets:**
| Target | Interpreter | What it does | Status |
|---|---|---|---|
| config | ConfigInterpreter | Writes to per-source YAML config files | Working |
| metadata | MetadataInterpreter | Updates ORM records (SemanticAnnotation, Relationship) | Working |
| data | DataInterpreter | Executes validated SQL against DuckDB | Working |

**Fix flow:**
```
Detector → FixSchema (declares shape)
  ↓
Agent/User → FixInput (provides parameters)
  ↓
Bridge → FixDocument(s) (concrete operations)
  ↓
Interpreter → applies to config/metadata/data
  ↓
Scheduler → resets requires_rerun phase → re-runs → re-measures at gate
```

All detectors at Gate 1 declare fix schemas (all config-target). Gate 2 adds
metadata-target fixes (e.g., dimensional_entropy's `create_constraint`). Gate 3
adds investigation-only fixes (cross-table issues require human review).

**What's missing:** MCP `apply_fix` tool. There is a `fix` CLI but it is
outdated and needs updating. The infrastructure (models, bridge, interpreters,
schemas, scheduler integration) is complete.

## Data Layers

| Layer | DuckDB pattern | Created by | Purpose |
|---|---|---|---|
| raw | `raw_{table}` | import | Source data as-is (VARCHAR for CSV) |
| typed | `typed_{table}` | typing | Columns cast to inferred types |
| quarantine | `quarantine_{table}` | typing | Rows that failed type casting |
| enriched | `enriched_{view}` | enriched_views (Zone 2) | Fact + dimension JOINs |
| slice | `slice_{src}_{col}_{val}` | slicing_view (Zone 2) | Categorical slices |

## Entropy Measurement Points

There are two measurement contexts:

1. **Gate measurement** — `measure_at_gate()` called by scheduler at quality
   gate phases. Limited to analyses available at that zone. Drives fix decisions.
   Gate scores need to be persisted for eval (open question: how?).

2. **Entropy phase** (Zone 3) — re-runs ALL detectors with ALL analyses.
   Feeds Bayesian network for interdependency assessment. Persists
   `EntropyObjectRecord` + `EntropySnapshotRecord` to metadata.db.

The eval tests gate scores (what the system acts on at each zone).

## MCP Server — What an Agent Needs

| Capability | Current state | Needed for eval |
|---|---|---|
| Run pipeline | `analyze()` — runs full pipeline | Zone-aware: `analyze(path, zone="foundation")` |
| Read quality | `get_quality()` — reads final entropy state | Zone-specific: `get_quality(zone="foundation")` |
| Apply fix | Not exposed | `apply_fix(action, params, columns)` |
| Advance zone | Not exposed | `continue_pipeline(zone="enrichment")` |
| Zone status | Not exposed | `get_zone_status()` |

## Calibration Strategy

**Principle:** Fix and calibrate existing detectors before adding new ones.
Adding detectors before existing ones are solid creates dead code.

Each zone has its own calibration scope:
- **Zone 1:** 9 detectors, their fix schemas, the fix loop. Deep calibration
  first. Includes fixing injections and refining composites.
- **Zone 2:** 5 additional detectors, enrichment-dependent fixes. Calibrated
  after Zone 1 is solid.
- **Zone 3:** 2 new detectors (cross_table_consistency, business_cycle_health),
  Gate 3 (computation_review), Bayesian network assessment, ground truth
  metric verification. See zone-3 spec.

Ground truth metric verification (revenue, FCF, DSO) requires the full pipeline
through Zone 3 (graph_execution). This is separate from detector calibration.

## Open Question: Gate Score Persistence

Gate scores are ephemeral today. The eval needs to read them. Three options:

1. **Fix ledger:** Use the fix system's before/after measurement infrastructure
   to store gate scores. Natural fit — the fix loop already measures at gate.
2. **Return to MCP caller:** `measure_at_gate()` returns scores to the caller
   (MCP server or CLI). The caller persists or keeps in memory. Lightweight,
   no schema changes.
3. **EntropySnapshotRecord:** Extend with a gate identifier and filter on read.
   Reuses existing persistence but needs schema changes and filtering logic.
