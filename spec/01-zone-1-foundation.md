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
- `score = 1.0 - parse_success_rate` (normal case)
- `score = score_fallback (0.5)` if decision_source == "fallback"
- Early return: score 0 if parse_success_rate == 1.0

**What triggers it:**
- Removal of type patterns from `typing.yaml` → fallback → 0.5
- Columns with >50% unparseable values → low parse_success_rate → high score

**What does NOT trigger it:**
- Sparse corruption (3% garbage): parse_success_rate ≈ 0.97 → score 0.03.
  The garbage goes to quarantine; type inference succeeds.

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
- Confidence penalty: +0.3 × max(0, 1.0 - confidence)

**What triggers it:** Semantic phase failure or truly meaningless column names
where even LLMs can't generate descriptions (very rare).

**What does NOT trigger it:** Abbreviated names (vid, pt, amt). LLMs handle
these well. All columns typically score 0.00–0.03.

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

**Measures:** Quality of detected relationships as a weighted composite.

**Scoring (weighted average):**
- Referential integrity: `1.0 - (left_ri / 100)` × weight 0.5
- Cardinality: verified=0.1, mismatch=0.7, unknown=0.4 × weight 0.3
- Semantic clarity: confirmed=0.1, unconfirmed=0.3, unknown=0.6 × weight 0.2

**What triggers it:** Large-scale RI violations (30%+), cardinality mismatches,
unconfirmed relationships.

**What does NOT trigger it:** Small orphan rates (5%). The weighted composite
dilutes the signal: 5% orphans → score ≈ 0.18.

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

### Solid (test these)

| Detector | Why it's solid |
|---|---|
| outlier_rate | Statistical signal, clear scoring curve, well-tested sensitivity |
| benford | Mathematical test (chi-square), strong signal when violated |
| null_ratio | Direct measurement (score = null_ratio). Simple, correct |
| join_path_determinism | Deterministic graph analysis. Sound logic |

### Needs refinement (test with caveats)

| Detector | Issue | Fix direction |
|---|---|---|
| type_fidelity | Only fires on type inference failures. 3% value corruption → 0.03 score | Add quarantine rate as a sub-signal. We already log it during typing — simple to expose. This gives type_fidelity a value-level signal without a new detector |
| unit_entropy | Checks metadata presence, not value consistency. The LLM (semantic phase) determines whether a column should have a unit — this is fine | Clarify its purpose in docs: it measures whether the pipeline successfully identified and declared units, not whether values are consistent. Rename or annotate accordingly |
| temporal_entropy | The "unmarked datetime" case (score 0.6) is worth keeping — temporal column identification is critical downstream for slicing, temporal drift, etc. The LLM usually finds these, so a high score here means something genuinely went wrong | Keep the scoring. The nervousness is justified: missing temporal roles break Zone 2 |
| relationship_entropy | Weighted composite dilutes per-signal clarity. Has never fired in practice. Relationships are proposed greedily by the relationships phase and confirmed by the LLM, so the composite averages over many "good enough" joins | Needs a different formula or evaluation approach. The RI component alone is meaningful but gets buried. Observe before rewriting |

### Undertested (fix the injection, not the detector)

| Detector | Issue | Fix direction |
|---|---|---|
| business_meaning | Scores 0.00–0.03 on abbreviated names (vid, pt) because LLMs handle these easily. But the scoring logic is sound — confidence penalty (`+0.3 × max(0, 1.0 - confidence)`) should fire on genuinely meaningless names | Test with truly garbage column names (e.g. `rrFlp_11_zp00`, `x7q_m2`). If LLM confidence drops, the detector works. Current injection is too mild, not the detector |

---

## Injection Analysis — Medium Strategy at Gate 1

For each injection in the medium strategy, what happens at Gate 1:

| # | Injector | Target | Assigned detector | Gate 1 score | Verdict |
|---|---|---|---|---|---|
| 1 | corrupt_types (3%) | journal_lines.debit | type_fidelity | ~0.03 | ⚠️ Too subtle. 97% parse success. Rows go to quarantine. |
| 2 | introduce_nulls (15%) | journal_lines.cost_center | null_ratio | ~0.15 | ⚠️ Below 0.3 threshold. Rate too low. |
| 3 | inject_outliers (5%, 10x) | journal_lines.credit | outlier_rate | ~0.40 | ✅ Detects. 5% at 10x is well outside IQR. |
| 4 | break_benford (60% round) | bank_transactions.amount | benford | ~0.85 | ✅ Detects. Severely non-compliant distribution. |
| 5 | inject_temporal_drift | bank_transactions.amount | temporal_drift | N/A | ❌ Zone 2 detector (needs DRIFT_SUMMARIES). |
| 6 | mix_units (10%, 1.1x) | invoices.amount | unit_entropy | ~0.1 or 0.8 | ⚠️ Wrong signal. Detector checks metadata, not values. |
| 7 | obscure_column_names | invoices.(vid,pt) | business_meaning | ~0.02 | ⚠️ LLMs handle abbreviations. Near-zero score. |
| 8 | corrupt_dates (all rows) | payments.date | temporal_entropy | ~0.1 | ⚠️ Typing handles mixed formats → DATE → aligned. Should target type_fidelity: use formats typing can't parse → quarantine → type_fidelity fires → add_type_pattern fix → temporal_entropy benefits downstream |
| 9 | break_ref_integrity (5%) | payments.invoice_id | relationship_entropy | ~0.18 | ⚠️ Composite dilutes 5% orphan signal. |
| 10 | create_mutual_exclusivity | journal_lines.debit/credit | dimensional_entropy | N/A | ❌ Zone 2 detector (needs SLICE_VARIANCE). |
| 11 | break_gl_invoice_match | invoices.amount | cross_table_consistency | N/A | 🚫 Detector does not exist. |
| 12 | break_payment_bank_match | payments.amount | cross_table_consistency | N/A | 🚫 Detector does not exist. |
| 13 | drift_formula (2%) | trial_balance.debit_balance | derived_value | N/A | ❌ Zone 2 detector (needs CORRELATION). |
| 14 | break_trial_balance (3%) | trial_balance.credit_balance | derived_value_consistency | N/A | 🚫 Detector does not exist. |

**Gate 1 summary:** 2 of 14 injections detected. 5 are not detectable at Gate 1
(Zone 2 or missing detector). 7 run but don't fire.

## Root Causes (Gate 1 Only)

### Cause A: Injection-detector misalignment

Six Zone 1 detectors run but don't detect their assigned injection because the
detector measures a different property than what the injection corrupts.

| Injection | Corrupts | Detector measures | Gap |
|---|---|---|---|
| corrupt_types (3%) | Value content | Type inference metadata | Value corruption at low rates doesn't affect inference |
| introduce_nulls (15%) | Value presence | Null proportion | Aligned but rate too low for threshold |
| mix_units (10%) | Value consistency | Unit metadata declaration | Metadata vs. value-level check |
| obscure_column_names | Schema naming | LLM description capability | LLM capability vs. naming quality |
| corrupt_dates (all) | Value format | Type ↔ role alignment | Reassign to type_fidelity: use unparseable formats → quarantine → type_fidelity fires. After fix (add_type_pattern), temporal_entropy benefits downstream |
| break_ref_integrity (5%) | FK validity | Weighted RI composite | Composite dilutes small-rate signal |

### Cause B: Threshold vs. injection rate

Two detectors are aligned with their injection but the injection rate is below
the detection threshold:
- null_ratio: 15% injection → score 0.15 → threshold 0.3
- type_fidelity: 3% corruption → score 0.03 → threshold 0.3

### What this means for calibration

The eval cannot just assert "detector X should score > 0.3 for injection Y."
It needs to account for:
1. Whether the detector is DESIGNED to catch that injection type
2. Whether the injection rate is sufficient for the detector's scoring curve
3. Whether the injection targets the right detector at all

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
