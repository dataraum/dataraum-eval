# Zone 1: Foundation — Detailed Specification

> Zone 1 runs from data import through semantic understanding. It ends at
> the `quality_review` gate. This is where the system establishes types,
> profiles, relationships, and meaning. Nine detectors measure entropy here.

## Phases

```
import → typing → statistics → column_eligibility
                                → statistical_quality
                                → relationships
                                → temporal
                  → semantic (depends on relationships)
                  → quality_review [GATE 1]
```

**quality_review dependencies:** `["semantic", "statistical_quality"]`

## Available Analyses at Gate 1

| AnalysisKey | Phase | What it contains |
|---|---|---|
| TYPING | typing | TypeDecision per column: resolved_type, parse_success_rate, decision_source, detected_unit |
| STATISTICS | statistics + statistical_quality | StatisticalProfile per column: null_ratio, outlier ratios (IQR/Z-score), Benford compliance, distribution stats. StatisticalQualityMetrics: benford_analysis, outlier_detection |
| SEMANTIC | semantic | SemanticAnnotation per column: semantic_role, entity_type, business_name, business_description, confidence, unit_source_column, business_concept |
| RELATIONSHIPS | relationships | Relationship records: from/to table+column, join_confidence, cardinality, evidence (referential integrity, Jaccard similarity) |

## Detectors

### 2.1 type_fidelity

**Measures:** Did the typing phase infer a real type or fall back to VARCHAR?

**Scoring:**
- `score = max(1.0 - parse_success_rate, boost(quarantine_rate))`
- Boost function: `((1+rate)²/-log₁₀(rate))-0.5`, clamped [0,1]
  Maps: 1%→0.01, 3%→0.20, 5%→0.35, 8%→0.56, 15%→1.0
- `score = score_fallback (0.5)` if decision_source == "fallback"

**What triggers it:**
- Removal of type patterns from `typing.yaml` → fallback → 0.5
- Columns with >50% unparseable values → low parse_success_rate → high score
- Quarantine rates above ~5%: rows that failed type casting during resolution

**What does NOT trigger it:**
- Very sparse corruption (1-2% garbage): boost(0.02)≈0.06, below threshold.

**Fix schema:** `add_type_pattern`
- Target: config → `phases/typing.yaml`
- Fields: pattern_name, regex, strptime_expression
- Operation: merge into overrides.type_patterns
- Requires rerun: typing

**Fix loop:** Fix adds custom pattern → typing re-runs → column parses → score drops.

---

### 2.2 null_ratio

**Measures:** Proportion of NULL values. Score = null_ratio directly.

**Scoring:**
- `score = null_ratio` from StatisticalProfile
- Accepted columns: floor at `score_accepted (0.10)`
- Impact levels: minimal (<0.05), moderate (<0.20), significant (<0.50)

**What triggers it:** Any null rate above threshold.

**Fix schema:** `accept_finding`
- Target: config → `entropy/thresholds.yaml`
- Operation: append column to `detectors.null_ratio.accepted_columns`
- Requires rerun: quality_review

**Fix loop:** Accept → column added to accepted list → score drops to 0.10.

---

### 2.3 outlier_rate

**Measures:** Fraction of values outside IQR fences (and/or Z-score thresholds).

**Scoring (piecewise linear on outlier_ratio):**
- 0% → 0.0, 1% → 0.15, 5% → 0.40, 10% → 0.65, 20%+ → 1.0
- CV attenuation: if robust_cv > 2.0, dampen by threshold/cv
- Accepted columns: floor at `score_accepted (0.20)`
- Skips: key, foreign_key roles

**What triggers it:** Statistical outliers at any rate above ~1%.

**Fix schema:** `accept_finding`
- Target: config → `entropy/thresholds.yaml`
- Operation: append to `detectors.outlier_rate.accepted_columns`
- Requires rerun: quality_review

---

### 2.4 benford

**Measures:** Whether first-digit distribution follows Benford's Law (chi-square
test + Cramér's V effect size).

**Scoring:**
- Compliant (p > 0.01): gradient 0.1 → 0.7
- Non-compliant (p ≤ 0.01): 0.7 + 0.3 × min(1.0, cramers_v / 0.5)
- Only runs on semantic_role == "measure"
- Minimum sample size: 100
- Accepted columns: floor at `score_accepted (0.20)`

**What triggers it:** Replacement of natural amounts with round numbers, uniform
distributions, or any process that destroys first-digit distribution.

**Fix schema:** `accept_finding`
- Target: config → `entropy/thresholds.yaml`
- Operation: append to `detectors.benford.accepted_columns`
- Requires rerun: quality_review

---

### 2.5 business_meaning

**Measures:** Whether the semantic phase produced a description, business_name,
and entity_type.

**Scoring (additive):**
- No description: 1.0
- Description + partial: 0.2–0.6
- All fields + concept: 0.0 (minus ontology bonus)
- Confidence penalty: +0.5 × max(0, 1.0 - confidence)

**What triggers it:** Garbage column names where the LLM reports low confidence
(0.2–0.4). Both tier 1 and tier 2 prompts instruct the LLM to set confidence
based on column NAME readability, not data inference. Tier 2 is told to
PRESERVE (not upgrade) low confidence on unreadable names.

**What does NOT trigger it:** Abbreviated names (vid, pt, amt). LLMs handle
these and correctly report high confidence since the abbreviations are
recognizable in context.

**Fix schema:** `document_business_meaning`
- Target: config → `phases/semantic.yaml`
- Fields: business_name, entity_type, business_description
- Operation: merge into overrides.annotations.{table}.{column}
- Requires rerun: semantic

---

### 2.6 unit_entropy

**Measures:** Whether a measure column has a declared unit (metadata check).

**Scoring:**
- No unit: 0.8
- Low confidence (<0.5): 0.5
- Declared or inferred: 0.1
- Only runs on semantic_role == "measure"

**What triggers it:**
- Removal of ontology guidance (is_unit_dimension, unit_from_concept)
- Columns where semantic phase can't link to a unit source

**What does NOT trigger it:** Value-level unit mixing (10% of amounts in
different currency). The detector checks metadata, not values.

**Fix schemas:**
1. `declare_unit` — config → `phases/typing.yaml`, merge into overrides.units.{table.column}, reruns typing
2. `set_unit_source` — config → `phases/semantic.yaml`, merge into overrides.units.{table.column}, reruns semantic

---

### 2.7 temporal_entropy

**Measures:** Alignment between data type and semantic temporal role.

**Scoring:**
- Datetime type + NOT marked timestamp: 0.6 (unmarked)
- NOT datetime type + marked timestamp: 0.8 (mismatch)
- Both aligned: 0.1
- Neither applicable: skipped

**What triggers it:**
- Removing date patterns → VARCHAR fallback + LLM assigns timestamp → mismatch (0.8)
- Datetime columns the LLM doesn't recognize as temporal

**What does NOT trigger it:** Mixed date formats where typing still parses
successfully. Example: a column has `2024-01-15`, `01/15/2024`, and `Jan 15 2024`
but the typing phase handles all variants → resolves to DATE → LLM assigns
timestamp role → type and role are aligned → score 0.1. The format corruption
is invisible because typing succeeded. If typing FAILS to parse rows (e.g. 15%
go to quarantine), that shows up on type_fidelity (parse_success_rate /
quarantine rate), not here. temporal_entropy only sees columns that survived
typing.

**Cross-detector interaction with type_fidelity:** Both detectors can lead to
`add_type_pattern` as a fix, but they fire on different conditions:
- **type_fidelity** fires when the column resolved as DATE but some rows went
  to quarantine (a pattern is missing → parse_success_rate < 1.0). The column
  IS typed correctly, but has potential to parse more.
- **temporal_entropy** fires when the column is VARCHAR but the LLM detected
  temporal meaning (type↔role mismatch: 0.8), or when a datetime column isn't
  marked with a temporal role (unmarked: 0.6).

In both cases, `add_type_pattern` is the fix. This already works.

**Fix schemas:**
1. `set_timestamp_role` — config → `phases/semantic.yaml`, merge into overrides.temporal_roles, reruns semantic
2. `add_type_pattern` — config → `phases/typing.yaml`, merge into overrides.type_patterns, reruns typing

---

### 2.8 relationship_entropy

**Measures:** Quality of detected relationships via max aggregation.

**Scoring (max of components):**
- Referential integrity: `sqrt(1.0 - left_ri / 100)` (sqrt-boosted)
- Cardinality: verified=0.1, mismatch=0.7, unknown=0.4
- Semantic clarity: confirmed=0.1, unconfirmed=0.3, unknown=0.6
- Final score: `max(ri, cardinality, semantic)`

**What triggers it:** Orphan rates above ~9% (sqrt(0.09)≈0.3), cardinality
mismatches, unconfirmed relationships.

**What does NOT trigger it:** Very small orphan rates (<5%). sqrt(0.05)=0.22,
still below 0.3.

**Fix schema:** `confirm_relationship`
- Target: config → `phases/relationships.yaml`
- Fields: relationship_type, expected_cardinality
- Key template: `{from_table}->{to_table}`
- Operation: merge into overrides.confirmed_relationships
- Requires rerun: relationships

---

### 2.9 join_path_determinism

**Measures:** Whether there's exactly one join path per target table.

**Scoring:**
- No relationships (orphan): 0.9
- All deterministic: 0.1
- Ambiguous: interpolated to 0.7 by ambiguity ratio
- `preferred_joins` config resolves known ambiguities

**What triggers it:** Multiple columns joining to the same target table,
lowered min_confidence exposing weak candidates.

**Fix schema:** `resolve_join_ambiguity`
- Target: config → `entropy/thresholds.yaml`
- Fields: preferred_column
- Key template: `{table}->{target_table}`
- Operation: merge into detectors.join_path.preferred_joins
- Requires rerun: quality_review

---

## Detector Assessment

Not all detectors are equal. Before calibrating, we need to know which ones
are worth testing. This assessment is based on what each detector ACTUALLY
measures and whether that measurement produces a meaningful signal.

### Calibrated — all passing (2026-03-12)

| Detector | Score | Calibration status |
|---|---|---|
| outlier_rate | 1.000 | Statistical signal, clear scoring curve |
| benford | 0.803 | Chi-square test, strong signal |
| null_ratio | 0.711 | Direct measurement (score = null_ratio) |
| type_fidelity | 0.585 | Boost function on quarantine rate. 8% quarantine → 0.585 |
| relationship_entropy | 0.447 | Max aggregation + sqrt-boosted RI. 20% orphans → sqrt(0.20)=0.447 |
| business_meaning | 0.375/0.350 | LLM confidence calibration. Garbage names → confidence 0.20–0.30 → penalty crosses threshold |
| temporal_entropy | 0.800 | Corrupt dates → VARCHAR fallback → type/role mismatch |
| join_path_determinism | 0.100 | No injection targets it; deterministic paths are correct behavior |

### Misaligned — injection doesn't test the detector

| Detector | Calibration status |
|---|---|
| unit_entropy | Working correctly (score 0.1 = units declared). The mix_units injection (10% × 1.1) is undetectable — see spec/02 for analysis |

---

## Injection Analysis — zone1-detection-v1 Strategy at Gate 1

Calibrated results after detector fixes and strategy tuning (2026-03-12):

| # | Injector | Target | Assigned detector | Gate 1 score | Verdict |
|---|---|---|---|---|---|
| 1 | corrupt_types (15%) | journal_lines.debit | type_fidelity | 0.585 | ✅ Boost function amplifies 8% quarantine rate |
| 2 | introduce_nulls (40%) | journal_lines.cost_center | null_ratio | 0.711 | ✅ Raised rate crosses threshold |
| 3 | inject_outliers (5%, 10x) | journal_lines.credit | outlier_rate | 1.000 | ✅ Well outside IQR |
| 4 | break_benford (60% round) | bank_transactions.amount | benford | 0.803 | ✅ Severely non-compliant distribution |
| 5 | inject_temporal_drift | bank_transactions.amount | temporal_drift | N/A | ⏭️ Zone 2 detector (needs DRIFT_SUMMARIES) |
| 6 | mix_units (10%, 1.1x) | invoices.amount | unit_entropy | 0.100 | ⚠️ Undetectable — see spec/02 |
| 7 | obscure_column_names | invoices.(rrFlp_11_zp00, xQ_v7kL) | business_meaning | 0.375/0.350 | ✅ LLM reports low confidence on garbage names |
| 8 | corrupt_dates (all rows) | payments.date | temporal_entropy | 0.800 | ✅ VARCHAR fallback → type/role mismatch |
| 9 | break_ref_integrity (20%) | payments.invoice_id | relationship_entropy | 0.447 | ✅ sqrt-boosted orphan rate |
| 10 | create_mutual_exclusivity | journal_lines.debit/credit | dimensional_entropy | N/A | ⏭️ Zone 2 detector (needs SLICE_VARIANCE) |
| 11 | break_gl_invoice_match | invoices.amount | cross_table_consistency | N/A | 🚫 Detector does not exist |
| 12 | break_payment_bank_match | payments.amount | cross_table_consistency | N/A | 🚫 Detector does not exist |
| 13 | drift_formula (2%) | trial_balance.debit_balance | derived_value | N/A | ⏭️ Zone 2 detector (needs CORRELATION) |
| 14 | break_trial_balance (3%) | trial_balance.credit_balance | derived_value_consistency | N/A | 🚫 Detector does not exist |

**Gate 1 summary:** 8 of 9 Zone 1 detectors pass. 1 misaligned (unit_entropy —
injection is undetectable, not a detector bug). 5 injections target Zone 2+
detectors or detectors that don't exist yet.

## Fix Loop Calibration

The E2E Override Validation (DAT-140) describes the fix loop test:
deliberately break config to trigger detectors, then apply fix overrides and
verify scores drop.

**Fix loop at Gate 1 — what the E2E validates:**

| Detector | Break method | Expected score | Fix action | Expected after |
|---|---|---|---|---|
| type_fidelity | Remove iso_date pattern | 0.50 (fallback) | add_type_pattern | 0.02 |
| unit_entropy | Remove currency concept from ontology | 0.80 (no unit) | declare_unit or set_unit_source | 0.10 |
| temporal_entropy | Remove date patterns | 0.60–0.80 | set_timestamp_role | 0.10 |
| outlier_rate | Remove accepted_columns | 0.65+ | accept_finding | 0.20 |
| benford | Remove accepted_columns | 0.70+ | accept_finding | 0.20 |
| join_path_determinism | Lower min_confidence to 0.2 | 0.40–0.70 | resolve_join_ambiguity | 0.10 |

This tests a different thing than injection detection: it tests the fix
mechanism (config break → elevated score → fix → score drop). Both matter
for calibration.

**Are we fixing the right things?** For config-target fixes at Gate 1, this
is straightforward: the fix modifies config, the detector re-measures, the
score drops. If the score drops, the fix worked. Note that `accept_finding`
doesn't remove outliers or nulls — it acknowledges them ("these are expected").
That's by design: the user/agent makes the judgment, the system records it.
Whether the system *recommends* the right fix is an agent/UX question (does the
MCP server suggest the correct fix action?), not a detector calibration question.
We test that separately once the MCP apply_fix tool exists.

## What the Eval Should Test at Zone 1

### Test 1: Detector recall against injections

For each injection that targets a Zone 1 detector, assert the detector scores
above threshold. **But first: the injection rates and detector assignments need
recalibration** (see Root Causes above).

### Test 2: Detector precision on clean data

On data generated with strategy=clean, all Gate 1 detector scores should be
below threshold. No false alarms.

### Test 3: Fix loop (E2E overrides)

Break config → verify elevated scores → apply fix → verify scores drop.
This validates the full fix mechanism independent of injection detection.

### Test 4: Gate score consistency

Verify that gate measurements are deterministic: same data + same config
= same scores (across runs).

## Path to Zone 1 Calibration

**Approach:** Streamline detectors first, then calibrate. Calibrating broken
detectors produces throwaway results.

### Step 1: Fix the detectors (dataraum-context)

| What | Where | Effort |
|---|---|---|
| Add quarantine rate to type_fidelity | dataraum-context | Small — quarantine counts already logged during typing. Merge into type_fidelity as a sub-signal |
| Observe relationship_entropy | dataraum-context | Wait — has never fired. Needs real-world data before rewriting formula. Greedy proposals + LLM confirmation means most relationships score well |
| Clarify unit_entropy in docs | spec | Small — document that it measures metadata completeness (LLM identifies unit-bearing columns), not value consistency |

### Step 2: Fix the test data (dataraum-testdata)

| What | Why |
|---|---|
| Raise injection rates where needed | null_ratio at 15% scores below 0.3 threshold. type_fidelity at 3% is invisible |
| Reassign detector_ids | 6 injections target wrong detectors. Fix the mapping to match what detectors actually measure |
| Fix injection #7 (obscure_column_names) | Use truly meaningless names (rrFlp_11_zp00) instead of abbreviations (vid, pt). Tests business_meaning's confidence penalty |

### Step 3: Fix infrastructure (dataraum-context)

| What | Why |
|---|---|
| Persist gate scores | Eval needs to read Gate 1 measurements (see 00-quality-zones.md §Persistence) |
| Update fix CLI | Exists but outdated. Needed for fix loop testing |
| MCP apply_fix tool | Needed for agent-driven fix loop |

### Step 4a: Calibrate detection

Inject → run pipeline → read gate scores → assert thresholds. No LLM, no
fix infrastructure needed. Pure data.

- Each injection that targets a Zone 1 detector → score above threshold
- Clean data → all scores below threshold (no false alarms)
- Gate score consistency: same data + same config = same scores

This is where most current problems live (injection misalignment, rates too
low). Steps 1–3 fix those. Step 4a proves the detectors work.

### Step 4b: Calibrate fixes (LLM-in-the-loop)

Detector fires → agent reasons about the signal → proposes fix → fix applied
→ score drops. Tests the full agent loop.

| Fix | Detector | What the agent determines |
|---|---|---|
| `accept_finding` | outlier_rate, benford, null_ratio | Whether the finding is expected (trivial) |
| `add_type_pattern` | type_fidelity | Correct regex + strptime for the unrecognized format |
| `declare_unit` / `set_unit_source` | unit_entropy | Correct unit declaration or source column |
| `set_timestamp_role` | temporal_entropy | Correct temporal role assignment |
| `document_business_meaning` | business_meaning | Meaningful name + description |
| `confirm_relationship` | relationship_entropy | Correct relationship type + cardinality |
| `resolve_join_ambiguity` | join_path_determinism | Correct preferred column |

Requires: gate score persistence + MCP apply_fix tool (Step 3).
Builds on: passing detection calibration (Step 4a).

### Deferred (do NOT start yet)

| What | Why deferred |
|---|---|
| New detectors | Existing detectors not yet calibrated. Adding more creates dead code |
| Zone 2+ calibration | Zone 1 must be solid first |
| Bayesian network calibration | Zone 3, least mature, most unknowns |

### Open questions

**cross_table_consistency:** What would it measure? The two injections that
target it (GL↔Invoice amount match, Payment↔Bank amount match) are cross-table
reconciliations. This is fundamentally a Zone 2+ problem — it requires enriched
views that JOIN fact tables. At Zone 1, tables are profiled independently.
No detector can catch cross-table mismatches without a JOIN. Defer.

**quarantine_rate as separate detector vs. merging into type_fidelity:**
Merging is better. type_fidelity already has `parse_success_rate` which is
essentially `1 - quarantine_rate`. The difference: `parse_success_rate` comes
from type inference statistics, while quarantine counts come from the actual
rows that failed casting. Using both signals in type_fidelity (inference
confidence + actual quarantine rate) gives a fuller picture without adding
a new detector.
