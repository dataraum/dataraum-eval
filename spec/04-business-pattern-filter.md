# Business Pattern Filter

> Detectors score patterns in isolation. They don't know that debit/credit mutual
> exclusivity is double-entry bookkeeping, that trial_balance distinct counts vary
> by account_type because that's how accounting works, or that LEFT JOIN NULLs are
> structural. The semantic agent does know. This spec bridges the gap.

## Problem

Multiple detectors flag expected business behavior as entropy:

| Detector | False positive | Real explanation |
|---|---|---|
| slice_variance | distinct_ratio=60x on trial_balance.debit_balance | Revenue accounts have 1 value, asset accounts have hundreds. That's the chart of accounts structure. |
| dimensional_entropy | conditional_dependency on debit | Debit is zero for credit-side entries. That's double-entry bookkeeping. |
| column_quality | Grade C on trial_balance.debit_balance "low cardinality in revenue slice" | Revenue accounts only post credits. Debit=0 is correct, not a quality issue. |
| outlier_rate | High outlier score on measures | Financial amounts span orders of magnitude by design (petty cash vs capex). |
| dimension_coverage | NULLs on enriched_payments.invoice_id__* columns | 20% orphan payments from FK injection — but natural orphan rates exist too (advance payments). |
| cross_table_consistency | trial_balance fails on clean data | The equation check is wrong, or the data generation doesn't guarantee it. Neither is an injection signal. |

The root cause: detectors measure statistical deviation, but some deviations ARE the
business logic. The semantic agent already has the context to distinguish them.

## Design Principle

**Detectors stay pure.** They measure what they measure — statistical properties,
pattern frequencies, spread metrics. They don't interpret business context.

**A separate filter contextualizes.** After detection, before scoring/gating, a
business pattern filter asks: "is this pattern explained by the column's business role?"

This keeps the measurement honest and the interpretation explicit. When a pattern IS
explained by business context, the score gets annotated — not zeroed. The gate can then
use the annotation to decide whether to count it as a violation.

## Mechanism: LLM Classification

A quick Haiku call per detector finding, with strongly typed Pydantic response.

### Why LLM, not rules

Rule-based approaches fail here because:
- The patterns are domain-specific (double-entry is financial, not universal)
- The combinations are combinatorial (measure + foreign_key + grain + relationship)
- New domains (marketing, supply chain) would need new rules
- The semantic agent's business_description is free text — rules can't parse it

A small LLM call is the right tool: it reads the business context (which is already
structured text from the semantic agent) and makes a yes/no classification.

### Why Haiku

- This is classification, not generation. Haiku is accurate enough.
- ~100ms per call, ~$0.001 per call
- A full pipeline has ~50 columns × ~5 detectors = ~250 findings, but most are
  score=0.0 and get filtered out. Realistic: 20-40 calls per pipeline run.
- Total cost: ~$0.04, ~4 seconds (parallelized)

### Input Schema

```python
class BusinessPatternCheck(BaseModel):
    """Input to the business pattern filter."""

    # What the detector found
    detector_id: str
    pattern_description: str  # Human-readable: "distinct_ratio=60x across slices"
    score: float

    # Column context (from semantic agent)
    table_name: str
    column_name: str
    semantic_role: str  # key, measure, dimension, timestamp, foreign_key, attribute
    business_name: str
    business_description: str

    # Table context
    table_description: str
    table_grain: list[str]  # e.g. ["period", "account_id"]

    # Relationship context (if foreign_key)
    relationship: str | None  # e.g. "payments.invoice_id → invoices.invoice_id"

    # Sibling columns (other columns on this table with their roles)
    sibling_context: list[dict[str, str]]  # [{name, role, business_name}]
```

### Output Schema

```python
class PatternVerdict(BaseModel):
    """LLM classification of whether a detected pattern is expected business behavior."""

    expected: bool  # True = this pattern is explained by business context
    confidence: float  # 0.0-1.0, how sure the LLM is
    reason: str  # One sentence: why this is/isn't expected
    business_rule: str | None  # If expected: what business rule explains it
```

### Prompt (sketch)

```
You are classifying whether a data quality finding is EXPECTED business behavior
or a REAL data problem.

A detector found this pattern:
- Detector: {detector_id}
- Finding: {pattern_description}
- Score: {score}

Column context:
- {table_name}.{column_name} ({semantic_role}): {business_description}
- Table: {table_description}
- Table grain: {table_grain}
{relationship context if applicable}

Other columns on this table:
{sibling_context}

Is this pattern expected given the business context?

Rules:
- Mutual exclusivity between debit/credit columns in double-entry accounting: EXPECTED
- Low cardinality in one slice when the table is segmented by account type: EXPECTED
- NULLs in FK-joined dimension columns when the relationship allows orphans: EXPECTED
- High distinct_ratio across slices when the grain varies by slice dimension: EXPECTED
- Outliers in financial measures that span petty cash to capital expenditure: EXPECTED
- Temporal drift at month boundaries in financial data: investigate, not auto-expected
- Actual data corruption (type mismatches, broken references): NOT expected
```

### Where It Runs

**Option A: Post-detection filter in the entropy phase.**
After detectors run, before scores are persisted. Each EntropyObject with score > 0
gets a BusinessPatternCheck. If `expected=True` with `confidence > 0.8`, annotate
the object with `expected_business_pattern=True` and the `business_rule`. Gate
measurement can then exclude or discount these.

**Option B: Inside entropy_interpretation (existing LLM phase).**
The interpretation phase already runs LLM calls per column. Add the pattern check
as part of the interpretation prompt — "these are the detector findings for this
column; which are expected business patterns?" This batches the calls and reuses
the existing LLM infrastructure.

**Option C: Standalone phase between entropy and entropy_interpretation.**
A dedicated `business_pattern_filter` phase. Clean separation but adds another phase.

**Recommendation: Option A** — run inline during the entropy phase, parallel with
detection. The entropy phase is currently non-LLM (~0.4s). Adding 20-40 Haiku calls
(~4s parallelized) is acceptable. It keeps the filter close to the measurement and
the annotation travels with the EntropyObject.

If latency is a concern, Option B reuses entropy_interpretation's LLM calls but
makes the dependency chain messier — the filter should apply before gates, not after.

## Score Handling

When a pattern is classified as expected:

```python
@dataclass
class EntropyObject:
    # ... existing fields ...
    expected_business_pattern: bool = False
    business_rule: str | None = None
    filter_confidence: float = 0.0
```

**Gate behavior:**
- `expected_business_pattern=True` AND `confidence >= 0.8` → excluded from
  violation assessment (same as `accepted=True` in fix system)
- `expected_business_pattern=True` AND `confidence < 0.8` → still scored but
  annotated in gate output for human review
- `expected_business_pattern=False` → normal scoring

**Context document (get_context):**
- Show the pattern as "expected: {business_rule}" instead of a quality issue
- This helps the downstream AI agent understand the data correctly

## Which Detectors Benefit

| Detector | What gets filtered | Impact |
|---|---|---|
| slice_variance | distinct_ratio, outlier_spread from grain/account_type variation | Most false positives eliminated |
| dimensional_entropy | conditional_dependency, mutual_exclusivity from accounting rules | debit/credit patterns become documented, not flagged |
| column_quality | LLM quality grades on expected patterns | Grades become more accurate |
| outlier_rate | Financial measures with natural wide ranges | Score reduction on legitimate spread |
| benford | Measures where Benford's law doesn't apply (balances vs transaction amounts) | Fewer false flags on balance columns |
| cross_table_consistency | Validation failures on structural issues | Scoping to real data mismatches |
| dimension_coverage | NULLs from expected orphan relationships | Natural orphan rates distinguished from injected ones |
| null_ratio | NULLs from LEFT JOIN structure, optional fields | Structural NULLs no longer flagged |

## What This Doesn't Fix

- **cross_table_consistency table_ids scoping** — the validation phase putting all
  table IDs on every result is a separate bug. The pattern filter won't fix attribution.
- **slice_variance threshold calibration** — the `2x threshold` normalization capping
  at 1.0 is a scoring bug. The filter reduces false positives but the scoring should
  also be fixed independently.
- **Validation SQL quality** — the validation phase generating SQL that doesn't catch
  our specific injections is a validation phase problem, not a filtering problem.

## Implementation Order

| Step | What | Blocked by |
|---|---|---|
| 1 | Add `expected_business_pattern`, `business_rule`, `filter_confidence` to EntropyObject | — |
| 2 | Create `BusinessPatternCheck` + `PatternVerdict` Pydantic models | — |
| 3 | Write the classification prompt with domain examples | — |
| 4 | Wire into entropy phase: post-detection filter on score > 0 objects | Steps 1-3 |
| 5 | Update gate measurement to respect `expected_business_pattern` | Step 1 |
| 6 | Update get_context formatting to show expected patterns | Step 1 |
| 7 | Calibrate: run on zone1/2/3 data, verify false positives suppressed, true positives kept | Steps 4-5 |

## Open Questions

- **Batch or per-finding?** Batching by table (all findings for journal_lines in one
  call) reduces calls but makes the prompt larger. Per-finding is simpler and more
  parallelizable. Start per-finding, batch later if cost/latency matters.
- **Cache results?** Same column + same detector + same pattern = same verdict across
  runs. Could cache in metadata.db to avoid re-calling on pipeline re-runs.
- **Threshold for confidence?** Starting at 0.8. May need tuning — too low and real
  problems get suppressed, too high and the filter is toothless.
- **Does this replace the documented_patterns config?** dimensional_entropy has a
  `documented_patterns` list in config. The pattern filter automates what that config
  does manually. Could coexist (config = user-confirmed, filter = LLM-suggested) or
  the filter could generate config entries automatically.
