# Eval history — pre-reset record

> Moved out of `CLAUDE.md` in the 2026-06-10 context reset. This is the
> historical record: dated results tables, the DAT-370 slice log, accumulated
> learnings, and the tool-surface validation plan. The **method** lives in
> `entropy_eval_architecture.md`; current epic state lives in Jira (DAT-442)
> and session memory. Nothing here constrains new work.

## Current slice (DAT-370, 2026-05-27) — what actually ran

The `addSourceWorkflow` slice runs phases **up to `semantic_per_column`** plus two
stage-level detect steps that run the detectors their phases declare in
`pipeline.yaml`:

- **`detect_table`** (per child workflow) — table-local detectors scoped to each
  child's typed table: `typing→type_fidelity`, `statistics→null_ratio`.
- **`detect_source`** (after the reduce; `fix/dat-370-source-level-detectors`) —
  `semantic_per_column`'s detectors, source-wide: `business_meaning`,
  `unit_entropy`, `temporal_entropy`, `benford`. (`outlier_rate` CUT, DAT-442.)

Verified end-to-end through Temporal on the fix branch:

| Strategy | Detector | Result |
|---|---|---|
| detection-v1 | `null_ratio` (journal_lines.cost_center) | ✅ pass |
| detection-v1 | `benford` (bank_transactions.amount) | ✅ pass |
| detection-v1 | `unit_entropy` (invoices.amount) | xfail (known-misaligned) |
| detection-v1 | `business_meaning` (invoices.*) ×2 | xfail/xpass (LLM-nondeterministic) |
| detection-typing-v1 | `type_fidelity` (journal_lines.debit) | ✅ pass |
| detection-typing-v1 | `temporal_entropy` (payments.date) | ✅ pass |

**History:** DAT-370 originally orphaned `semantic_per_column`'s five detectors —
it ran the phase but wired no detect step for them (only `detect_table` for
table-local phases). Eval caught this; the fix added `detect_source`. The
detectors were never broken, only unwired.

Still **skipped** by `test_detector_recall.py` (slice-2 phases not in the chain):
`relationship_entropy`, `dimensional_entropy`, `derived_value`, `temporal_drift`,
`cross_table_consistency` (in `semantic_per_table` / `enriched_views` /
`validation` / …). As those phases get wired, move detector ids out of
`OUT_OF_SLICE_REASON` / into `CURRENT_SLICE_DETECTORS` in
`test_detector_recall.py` and the assertions re-apply. The results table below is
the **pre-Temporal baseline** (all phases ran in-process) — the target once the
full workflow chain lands.

## Detection Calibration Results (2026-04-17, detection-v1) — pre-Temporal baseline

**Detection recall: 12/14 pass, 2 xfail, 2 non-deterministic (LLM)**

### Passing (score > 0.3)

| Detector | Target | Score | Notes |
|---|---|---|---|
| null_ratio | journal_lines.cost_center | ~0.71 | 40% injection rate |
| outlier_rate | journal_lines.credit | 1.000 | 5% at 10x multiplier (detector since CUT) |
| benford | bank_transactions.amount | ~0.80 | 60% round numbers |
| temporal_drift | bank_transactions.amount | 1.000 | 1.35x shift after mid-year (detector since CUT) |
| relationship_entropy | payments.invoice_id | ~0.45 | sqrt-boosted 20% orphan rate |
| dimensional_entropy | journal_lines.debit/credit | ~0.70 | Natural debit/credit mutex |
| derived_value | journal_lines.net_amount | ~0.71 | 10% formula drift, boost curve |
| cross_table (gl_invoice) | invoices.amount | pass | 15% amount corruption, FK join |
| cross_table (payment_bank) | payments.amount | pass | 15% amount corruption, FK join |
| cross_table (trial_balance) | trial_balance.credit_balance | pass | 10% balance corruption |

### Non-deterministic (xfail strict=False)

| Detector | Target | Score | Notes |
|---|---|---|---|
| business_meaning | invoices.rrflp_11_zp00 | ~0.38 | LLM sometimes infers concept from data → ontology_bonus reduces score below threshold |
| business_meaning | invoices.xq_v7kl | ~0.35 | Same — shows XPASS when detection works, XFAIL when LLM grounding hides it |

### Known misaligned (xfail)

| Detector | Target | Root cause |
|---|---|---|
| unit_entropy | invoices.amount | Measures metadata completeness, not value consistency. Injection targets values |
| derived_value | trial_balance.debit_balance | Cross-table aggregate (TB vs GL), not within-table formula. Out of scope for derived_value |

### Detection-typing-v1 results (type-breaking)

| Detector | Target | Score | Notes |
|---|---|---|---|
| type_fidelity | journal_lines.debit | 0.585 | Boost function on 8% quarantine rate (boost since dropped) |
| temporal_entropy | payments.date | 0.800 | Corrupt dates → VARCHAR → type/role mismatch |

## Teach Loop Calibration (4b)

The old fix system (ResolutionOptions, FixSchema, apply_fix) was retired in
DAT-256. The teach system (DAT-251) replaced it. Teach loop tests live in
`calibration/tools/test_adhoc_teach_loop.py` (7 tests: 5 pass, 2 xfail for
config teach re-run bugs documented in handoff).

## Key Learnings (pre-reset era)

> Several of these describe boost-curve fixes that the DAT-442 reset later
> identified as the *smell* (grounding skipped). Kept for the record.

### Detector scoring needs non-linear amplification (SUPERSEDED)
Linear `score = rate` under-weights real problems. 8% quarantine means 8% of
your data is broken — that's not 0.08 severity. The `_boost_rate()` function
in type_fidelity used `((1+rate)^2/-log10(rate))-0.5` to map small rates to
scores. **The reset dropped boost curves: raw rates + ordering assertions.**

### LLM confidence must be calibrated at both tiers
The business_meaning detector relies on LLM confidence to catch garbage column
names. Without guidance, LLMs report 0.85-0.90 confidence on garbage names
because they infer meaning from data. The fix: add `<confidence_guidance>` to
BOTH tier 1 and tier 2 prompts, update the Pydantic field description, and
tell tier 2 to PRESERVE (not UPGRADE) confidence reflecting name readability.
Tier 2 was the main problem — it "upgraded" low tier-1 confidence to high.

### Weighted average composites hide problems
relationship_entropy's weighted average (0.5 RI + 0.3 cardinality + 0.2 semantic)
made 20% orphan rates invisible. Max aggregation with sqrt-boosted RI is direct:
the worst problem drives the score. (Reset: raw orphan rate, no sqrt-boost.)

### Injector dispatch must match strategy format names
The corrupt_dates injector uses human-readable format names (`DD/MM/YYYY`) for
dispatch. The strategy had strftime format strings (`%d/%m/%Y`). Nothing matched
→ fallback to isoformat → zero corruption. **Always verify injector output.**

### unit_entropy is correctly misaligned
The detector measures whether the pipeline identified and declared units
(metadata completeness). The mix_units injection corrupts values. These are
different things. The detector works — the injection doesn't test it.

### Documentation-debt detectors need fix-loop testing
dimensional_entropy measures intrinsic data complexity, not injected corruption.
Clean data scores 0.5-0.7 because the patterns are real business rules.
Injection delta is zero. The calibration test is: document_business_rule fix → score drops.

### derived_value scoring uses boost + formula chain attribution
The correlations dedup prefers sum over difference: `debit = net_amount + credit`
wins over `net_amount = debit - credit`. Injecting drift on net_amount causes the
debit formula to break, so the score appears on `debit`, not the injected column.
The `_find_score` fallback handles this by checking all columns in the table.

### Cross-table validations need explicit FK join paths
LLM agents fall back to fuzzy date+amount matching when FK paths aren't obvious,
masking corruption. Testdata must include explicit FK columns (e.g., Invoice.entry_id,
BankTransaction.payment_id) and validation specs must mandate FK-first join strategy.

### Aggregate evaluator must check rates against tolerance
The validation agent's aggregate handler was returning `passed=True` unconditionally.
Must extract orphan_rate/violation_rate from results and compare against the
tolerance parameter. Otherwise cross-table validations never fail.

## Tool Surface Validation (DAT-191)

After each phase of the MCP Practitioner API (DAT-173), we run tool-level eval tests
against the same ground truth data used for detector calibration. See
[DAT-191](https://linear.app/dataraum/issue/DAT-191/eval-tool-surface-validation-per-phase-ground-truth-regression)
for the full plan.

### MCP Tool Surface (Phase 1 shipped)

9 active tools, 6 deferred. See `vendor/dataraum-context/plans/mcp-interface-design/`
for full design docs. (Note: the engine-side MCP surface was later moved to
`reference/mcp/` as dead code, DAT-369.)

| Tool | Verb | Status |
|---|---|---|
| `look` | "What am I looking at?" | Phase 1 ✅ |
| `measure` | "How much entropy?" | Phase 1 ✅ |
| `begin_session` | "Start investigation" | Phase 1 ✅ |
| `query` | "Answer my question" (LLM) | Phase 1 ✅ |
| `run_sql` | "Execute this SQL" | Phase 1 ✅ |
| `add_source` | "Register data source" | Phase 1 ✅ |
| `why` | "Why this score?" (LLM) | Phase 2 |
| `hypothesize` | "What if X?" (BBN) | Phase 3 |
| `teach` | "Tell the system something" | Phase 3 |

Retired tools: `get_quality`, `apply_fix`, `get_context`, `analyze`,
`continue_pipeline`, `discover_sources`, `export`. `fix` absorbed into `teach`.

### Test rounds

Tests live in `calibration/tools/` and assert against `ground_truth.yaml` (exact
financial figures) and `entropy_map.yaml` (known injections). One round per phase:

| Round | After phase | Tests |
|---|---|---|
| 1 | look + measure + begin_session + run_sql | Schema correctness, measurement points, SQL enrichment |
| 2 | why + query | Evidence targeting, financial accuracy, ground truth regression |
| 3 | hypothesize + teach | BBN predictions, teach loop (hypothesize → teach → measure) |
| 4 | deliver + report + session lifecycle | Goodhart firewall, assumption integration, end-to-end flow |

`query` and `why` tests are LLM-in-the-loop (mark `@pytest.mark.llm`). All others
are deterministic. Each round is additive.

### Handoff protocol

`vendor/dataraum-context/.claude/handoff.md` is updated by `/implement` sessions
in the context repo and consumed by `/accept` in this repo. Each entry describes
what changed, what it affects, and what to calibrate.

## Old backlog notes

- Update network.yaml with cross_table and business_cycle nodes + edges
  (note: the Bayesian network was deleted in DAT-442 — superseded)
- unit_entropy: accept misalignment or create separate injection
- Resolved by the DAT-442 reset: the old outlier_rate / temporal_drift "verify 1.0
  scores" items — both detectors CUT. The outlier_rate false-positive concern was
  confirmed: linear IQR flags 25%+ of legitimate financial heavy-tail values.
- Roadmap pointers: business pattern filter, pipeline YAML redesign, showcase
  playbooks ([Pipeline Redesign](https://linear.app/dataraum/project/pipeline-redesign-yaml-driven-dag-entropy-measurement-9c6b0d33aa5c))
