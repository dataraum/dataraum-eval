# Zone 3: Interpretation — Outline

> Zone 3 is the tail of the pipeline. It uses a Bayesian network to assess
> entropy interdependencies, LLM agents for interpretation and validation,
> and computes business metrics. This zone is the least mature.
>
> This document is intentionally thin. Zone 3 calibration follows Zone 2.
> Do not invest here until Zone 1 and Zone 2 detectors are calibrated.

## Phases

```
business_cycles (LLM — detects fiscal periods)
validation (LLM — generates and executes validation SQL)
entropy (Bayesian network — re-runs all detectors, models interdependencies)
  ├── entropy_interpretation (LLM — narratives + resolution actions) [LEAF]
  └── graph_execution (LLM — computes business metrics) [LEAF]
```

**Topology:** Two leaf nodes (entropy_interpretation and graph_execution).
The entropy phase is the bottleneck — everything upstream must complete before
it runs.

## What the Entropy Phase Does

1. Re-runs ALL registered detectors with all available analyses
2. Persists `EntropyObjectRecord` per detector per target (to metadata.db)
3. Builds Bayesian network (`EntropyNetwork`) from detector results
4. Computes per-node probabilities (worst_p_high, mean_p_high) across intent nodes
5. Creates `EntropySnapshotRecord` with network state (overall_readiness, counts)

The Bayesian network models interdependencies between entropy dimensions — e.g.,
poor type fidelity increases the probability of poor unit detection. This is
distinct from individual detector scores.

## Phases Without Entropies (Gaps)

| Phase | What it produces | Entropy potential |
|---|---|---|
| business_cycles | DetectedBusinessCycle records | Could measure: cycle detection confidence, period coverage, alignment with temporal patterns |
| validation | ValidationResultRecord | Could measure: validation pass rate, constraint violation severity, cross-table consistency |

These phases use LLM agents and produce structured results, but no entropy
detectors consume their output. Building detectors for these is future work.

## Ground Truth Metrics

The graph_execution phase computes business metrics (revenue, FCF, DSO).
Ground truth verification (comparing computed values against `ground_truth.yaml`)
requires the full pipeline through this phase.

This is separate from detector calibration — it tests the analytical correctness
of the system end-to-end, not the entropy detection.

## Open Items (Deferred)

- Should Zone 3 have a gate? Before graph_execution? After entropy?
- What detectors should business_cycles and validation produce?
- How should the Bayesian network assessment be calibrated?
- The entropy_interpretation phase produces resolution actions via LLM — how
  do these relate to the detector-declared fix schemas?
- Graph execution correctness: how to validate computed metrics against
  ground truth without running the full pipeline in every eval?
