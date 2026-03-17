# Zone 3: Interpretation

> Zone 3 runs from business cycles through graph execution. It ends at the
> `computation_review` gate (Gate 3). This zone detects cross-table
> inconsistencies, assesses business cycle health, builds a Bayesian network
> for interdependency assessment, and computes business metrics.

## Phases

```
business_cycles (LLM — detects fiscal periods, entity flows, completion rates)
  → validation (LLM — generates and executes cross-table SQL checks)
  → computation_review [GATE 3]
  → entropy (Bayesian network — re-runs all detectors, models interdependencies)
    ├── entropy_interpretation (LLM — narratives + resolution actions) [LEAF]
    └── graph_execution (LLM — computes business metrics) [LEAF]
```

**Topology:** Gate 3 sits between the analysis phases (business_cycles,
validation) and the synthesis phases (entropy, interpretation, graph_execution).
This ensures cross-table and cycle-health problems are caught and fixable
before the Bayesian network incorporates them and before metrics are computed.

## Additional Analyses at Gate 3

| AnalysisKey | Phase | What it contains |
|---|---|---|
| BUSINESS_CYCLES | business_cycles | DetectedBusinessCycle records: cycle types, stages, entity flows, completion rates, confidence |
| VALIDATION | validation | ValidationResultRecord: LLM-generated SQL check results, pass/fail/error per check, severity |

These are new AnalysisKey values that need to be added to the enum.

## Additional Detectors at Gate 3

| Detector | Measures | Scope | Required analyses | Injection-testable? |
|---|---|---|---|---|
| cross_table_consistency | Cross-table reconciliation failures from validation checks | table | VALIDATION | Yes — via break_gl_invoice_match, break_payment_bank_match, break_trial_balance |
| business_cycle_health | Cycle detection quality: completion rates, confidence | table | BUSINESS_CYCLES | No — documentation-debt style, measures intrinsic cycle quality |

### Detector Categories

**Injection-testable** (recall test: inject → score rises above threshold):
- `cross_table_consistency`: Three existing injections corrupt one side of a
  cross-table relationship. The validation phase detects the mismatch via SQL.
  The detector converts validation failures to entropy scores.

**Documentation-debt detector** (no injection, calibrate via observation):
- `business_cycle_health`: Measures how well the pipeline detected business
  cycles. Clean financial data should produce high completion rates and
  confidence. The signal is intrinsic — there's no injection that "breaks"
  cycle detection. Calibration starts by observing what the phase produces
  on real data and learning from it.

## cross_table_consistency Detector

### Design

Consumes `ValidationResultRecord` from the validation phase. The validation
phase already generates and executes the SQL — the detector only scores the
results.

**Scope:** Table-level. Each validation check produces a result spanning
multiple tables. The detector attaches the score to the **primary table**
involved (e.g., trial_balance gets the score for the accounting equation check,
invoices for the GL match check).

**Required analyses:** `AnalysisKey.VALIDATION`

### Validation checks that feed this detector

| Validation ID | Check type | What it catches | Primary table | Severity |
|---|---|---|---|---|
| `double_entry_balance` | balance | Debits ≠ credits | journal_lines | critical |
| `trial_balance` | comparison | Assets ≠ Liabilities + Equity | trial_balance | critical |
| `orphan_transactions` | aggregate | FK orphan rates above threshold | per-relationship fact table | warning |
| `three_way_match` | comparison | PO/receipt/invoice amount disagreement | (if P2P data exists) | warning |

Additional validation specs (fiscal_period, sign_conventions, stage_date_ordering)
produce constraint/aggregate results that could also feed the detector, but are
lower priority for initial calibration.

### Scoring

Different check types need different score conversion:

| Check type | Score formula | Example |
|---|---|---|
| balance | `min(1.0, \|difference\| / magnitude)` with boost | $50k difference on $50M total → small raw ratio, boosted |
| comparison | `1.0 if !equation_holds else 0.0` (binary for critical checks) | Accounting equation either holds or doesn't |
| aggregate | `orphan_rate` with sqrt boost (same as relationship_entropy) | 5% orphans → boosted score |
| constraint | `min(1.0, violation_count / total_rows)` with boost | Sign convention violations |

**Aggregation across checks:** `max()` — worst validation failure drives the
table's score. Consistent with relationship_entropy's aggregation approach.

### Injections

Three injections target this detector. All exist in `baseline.yaml`, excluded
from zone1/zone2 strategies because the detector didn't exist.

| Injection | Target | Params | Validation check |
|---|---|---|---|
| break_gl_invoice_match | invoices.amount | 5% ratio, 0.8-1.3x factor | Caught by amount reconciliation SQL |
| break_payment_bank_match | payments.amount | 4% ratio, 0.9-1.2x factor | Caught by payment-bank reconciliation SQL |
| break_trial_balance | trial_balance.credit_balance | 3% ratio, 0.01-5.0 error range | Caught by `trial_balance` (accounting equation) |

**Note:** `break_trial_balance` was originally assigned to `derived_value_consistency`
in the injector. Reclassified here: trial balance is a cross-table aggregate of
journal_lines. When it doesn't match, it's the same class of problem as
invoices not matching GL — one side has the right number, the other doesn't.

### Fix schemas (planned)

| Action | Target | What it does |
|---|---|---|
| `investigate_reconciliation` | config | Resolution hint — no auto-fix for cross-table mismatches |
| `accept_finding` | config | Mark as reviewed, exclude from scoring |

Cross-table consistency issues require human investigation. The fix system
can note the finding as reviewed but can't automatically repair the data
mismatch between independent tables.

## business_cycle_health Detector

### Design

Consumes `DetectedBusinessCycle` records from the business_cycles phase.

The business_cycles phase is one of the strongest agentic phases — it produces
rich structured data about entity flows, cycle stages, completion rates, and
business value classifications. This data is directly consumed by graph_execution
to generate metrics. **Poor cycle detection → wrong metrics.** This makes
business_cycle_health a natural entry criterion for the computation zone.

**Scope:** Table-level (cycles span multiple tables, but attach to the
status_table or primary fact table).

**Required analyses:** `AnalysisKey.BUSINESS_CYCLES`

### What it measures

| Signal | Source field | Entropy mapping |
|---|---|---|
| Completion rate | `DetectedBusinessCycle.completion_rate` | Low completion → high entropy (stuck records, incomplete processes) |
| Detection confidence | `DetectedBusinessCycle.confidence` | Low confidence → high entropy (uncertain detection) |
| Cycle coverage | Number of detected cycles vs expected | Missing expected cycles → high entropy |

### Scoring approach (initial — learn first)

Start simple, refine after observing real output:

```
per_cycle_score = max(1.0 - completion_rate, 1.0 - confidence)
table_score = max(per_cycle_scores for cycles involving this table)
```

This is deliberately naive. The business_cycles phase produces rich data
(stages, entity_flows, data_quality_observations). After observing what it
produces on real financial data, we may want more nuanced scoring.

### Calibration approach

No injection. Instead:
1. Run full pipeline on clean test data
2. Observe: what cycles are detected? What completion rates? What confidence?
3. Establish baseline: clean financial data with 12 months should produce
   well-detected cycles (order-to-cash, period-close, reconciliation)
4. Define threshold: what completion_rate / confidence = "good enough"?
5. Future: create targeted injections (e.g., delete status column values)
   if observation-based calibration proves insufficient

This follows the dimensional_entropy pattern — learn from the data first,
inject later if needed.

### Fix schemas (planned)

| Action | Target | What it does |
|---|---|---|
| `investigate_cycle_health` | config | Resolution hint for low completion |
| `accept_finding` | config | Mark as reviewed |

Like cross_table_consistency, cycle health issues require human investigation.

## Gate 3: computation_review

### Placement

After validation and business_cycles, before entropy and graph_execution.

**Rationale:** Don't compute metrics on data that has unresolved cross-table
inconsistencies or unreliable cycle detection. The entropy phase should
incorporate the post-fix state, not the pre-fix state.

### Mechanics

Same as Gate 1 (quality_review) and Gate 2 (analysis_review):

1. `measure_at_gate()` runs all detectors whose analyses are satisfied
   (now includes Zone 3 detectors requiring VALIDATION and BUSINESS_CYCLES)
2. `assess_contracts()` compares scores against contract thresholds
3. If violations: yields `EXIT_CHECK` event with scores + available fix schemas
4. Caller resolves: DEFER, ABORT, or FIX
5. If FIX: applies fix → resets affected phases → re-runs → re-measures
6. Repeats until no violations or caller defers

### What runs at Gate 3

All previously runnable detectors (Zone 1 + Zone 2) re-measured, plus:
- `cross_table_consistency` (requires VALIDATION)
- `business_cycle_health` (requires BUSINESS_CYCLES)

**Total detectors at Gate 3:** 16 (14 existing + 2 new)

## What the Entropy Phase Does

After Gate 3, the entropy phase:

1. Re-runs ALL registered detectors with all available analyses
2. Persists `EntropyObjectRecord` per detector per target (to metadata.db)
3. Builds Bayesian network (`EntropyNetwork`) from detector results
4. Computes per-node probabilities (worst_p_high, mean_p_high) across intent nodes
5. Creates `EntropySnapshotRecord` with network state (overall_readiness, counts)

The Bayesian network models interdependencies between entropy dimensions — e.g.,
poor type fidelity increases the probability of poor unit detection. This is
distinct from individual detector scores.

### Bayesian Network Updates

The network (config/entropy/network.yaml) needs updates to incorporate Zone 2+3:

**New observable nodes:**

| Node | Layer | Dimension | Sub-dimension | Parents |
|---|---|---|---|---|
| cross_table_consistency | computational | reconciliation | cross_table_consistency | (root — no causal parents, directly measured) |
| business_cycle_health | semantic | cycles | cycle_health | (root — no causal parents, directly measured) |

**New edges to intent nodes:**

| Edge | Strength | Rationale |
|---|---|---|
| cross_table_consistency → aggregation_intent | 0.8 | Cross-table disagreement makes aggregations unreliable |
| cross_table_consistency → reporting_intent | 0.7 | Can't report on inconsistent data |
| business_cycle_health → reporting_intent | 0.5 | Incomplete cycles affect report completeness |
| business_cycle_health → aggregation_intent | 0.4 | Cycle health contextualizes aggregation scope |

**Network gaps to reconcile:**

| Issue | Status |
|---|---|
| `formula_match` node name vs `derived_value` detector ID | Verify bridge mapping handles this |
| `aggregation_safety` node has no detector (inferred composite) | By design — verify inference works with real data |
| `dimensional_entropy` detector has no network node | Table-scoped; network is column-scoped. Needs design decision. |
| `column_quality` detector has no network node | Same issue — table-scoped detector, column-scoped network |

Table-scoped detectors (dimensional_entropy, column_quality, and the new
cross_table_consistency, business_cycle_health) don't map cleanly to the
per-column Bayesian network. Options: (a) broadcast table score to all columns,
(b) create table-level intent aggregation separate from column network,
(c) ignore in network, use at gate level only. Deferred — observe first.

## entropy_interpretation — Quick Check

The entropy_interpretation phase was working before quality gates were added.
It needs a quick validation, not recalibration:

- [ ] Columns with known problems get non-baseline interpretations
- [ ] Clean columns get filtered to baseline (p_high_threshold = 0.35)
- [ ] Resolution actions reference actual fix actions the system can apply
- [ ] LLM cost is reasonable (baseline filtering reduces calls)

**DAT-144:** The interpretation phase may produce novel resolution_actions
via LLM that don't map to detector-declared fix schemas. These are "on the fly"
fixes discovered during interpretation. The fix system currently only handles
detector-declared schemas — interpretation-generated actions are informational
only. Parked for DAT-144.

## Ground Truth Metrics

The graph_execution phase computes business metrics (revenue, FCF, DSO).
`ground_truth.yaml` exists in all test data directories with known values:

| Metric | Value (seed=42) | Source |
|---|---|---|
| total_revenue | $51.77M | ground_truth.yaml |
| total_expenses | $23.53M | ground_truth.yaml |
| gross_profit | $28.24M | ground_truth.yaml |
| DSO, DPO | per ground_truth.yaml | monthly breakdowns |
| FCF | per ground_truth.yaml | monthly breakdowns |

**Verification approach:**
1. Run full pipeline through graph_execution on clean data
2. Compare computed metrics against ground_truth.yaml values
3. Define acceptable tolerance per metric
4. Assert within tolerance

**Invariants** (must always hold, regardless of injections):
- journal_balanced = true
- trial_balance_balanced = true
- invoice_payment_matched = true
- bank_reconciliation_rate ≈ 89.51%

Ground truth verification is separate from detector calibration — it tests
analytical correctness end-to-end, not entropy detection.

## Strategy: zone3-detection-v1

Extends zone2-detection-v1 with cross-table injections:

**Zone 1+2 baselines (carried forward):**
- inject_temporal_drift (bank_transactions.amount, 1.35x)
- break_benford (bank_transactions.amount, round_numbers)
- introduce_nulls (journal_lines.cost_center, 40%)
- drift_formula (journal_lines.net_amount, 10% error)
- break_referential_integrity (payments.invoice_id, 20%)

**Zone 3 additions:**
- break_gl_invoice_match (invoices.amount, 5% ratio) → cross_table_consistency
- break_payment_bank_match (payments.amount, 4% ratio) → cross_table_consistency
- break_trial_balance (trial_balance.credit_balance, 3% ratio) → cross_table_consistency

**No injection for business_cycle_health** — observation-based calibration first.

**Injection rates may need tuning.** The baseline rates (3-5%) were set before
any detector existed. They may be too low for the detector's scoring curve to
cross threshold. Adjust after first calibration run.

## Implementation Order

| Step | What | Where | Blocked by |
|---|---|---|---|
| 0 | Add sqrt boost to `dimension_coverage` detector (Zone 2 fix, bundled here) | dataraum-context: detectors/semantic/dimension_coverage.py | — |
| 1 | Add `AnalysisKey.VALIDATION` and `AnalysisKey.BUSINESS_CYCLES` | dataraum-context: dimensions.py | — |
| 2 | Implement `cross_table_consistency` detector | dataraum-context: entropy/detectors/computational/ | Step 1 |
| 3 | Implement `business_cycle_health` detector | dataraum-context: entropy/detectors/semantic/ | Step 1 |
| 4 | Add `computation_review` gate phase | dataraum-context: pipeline/phases/ | Steps 2, 3 |
| 5 | Update network.yaml with new nodes + edges | dataraum-context: config/entropy/ | Steps 2, 3 |
| 6 | Create zone3-detection-v1 strategy | dataraum-eval: strategies/ | — |
| 7 | Calibrate cross_table_consistency | dataraum-eval: calibration/ | Steps 2, 4, 6 |
| 8 | Observe business_cycle_health | dataraum-eval: calibration/ | Steps 3, 4 |
| 9 | Quick check: Bayesian net + interpretation | dataraum-eval: calibration/ | Step 5 |
| 10 | Ground truth verification | dataraum-eval: calibration/ | Steps 4, 6 |

## Open Items

- Injection rates for cross_table_consistency: 3-5% may be too low — tune after first run
- business_cycle_health scoring: deliberately naive, refine after observing real output
- Table-scoped detectors in column-scoped Bayesian network: design decision deferred
- `formula_match` / `derived_value` naming mismatch: verify bridge mapping
- Zone 3 fix schemas: resolution hints only, no auto-fix for cross-table issues
- DAT-144: entropy_interpretation generating novel fix actions not in detector schemas
- ~~dimension_coverage at Gate 2: signal 0.2 from 20% orphans~~ Resolved: add sqrt boost (Step 0), same pattern as relationship_entropy. 20% → ~0.45
