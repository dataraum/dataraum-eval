# DAT-620 Lane 1 — the A-vs-B kill-gate rig

**Status:** scoped, not built. Disposable probe (`scripts/probes/dat620/`); the verdict
is recorded in `entropy_eval_architecture.md`, then this dir is deleted.

## Context — the question this lane answers

DAT-620 ("grounding heart") proposes a new value→concept **labeler + binding table +
teach + phase** so the SQL/graph agent stops improvising the row filter for finance
metrics. Before building any of that machinery, we test the premise on data.

Code-grounded facts that frame the question:

- The metric path is wrong because the graph agent is **starved**: `graphs/context.py`
  drops `top_values` (~810) and loads no drivers; `graphs/agent.py:666` feeds the LLM a
  bare `SELECT DISTINCT … LIMIT 5`.
- In **wide** data there is no labeler to build — the semantic agent already maps
  `business_concept: revenue → that column` (`graphs/field_mapping.py:70-140`). Feed
  `top_values` + existing labels and the fix is just DAT-616.
- In **long-format** data (one `amount` + an `account_type` discriminator — the BookSQL
  shape this epic targets) there is a **genuine gap**: the semantic agent labels
  `account_type` a dimension and `amount` a measure with `business_concept = null`; it
  never says *which `account_type` values are revenue*. Slices/drivers are statistical
  (`{dimension, value, effect, support}`), never semantic. Nothing produces value→concept
  membership.
- The semantic agent's concept labeling is **not calibrated today** — only the
  `business_meaning` naming-clarity detector and stock/flow teach-closure are tested. We
  have no precision/recall number for the thing this epic depends on.

So the gap is real but its size is unknown. Three tiers of fix, cheapest first:

- **A — just feed it.** Serve `top_values(account_type)` + the ontology concept list;
  let the agent map values→concept inline. No persistence, no teach. (≈ DAT-616 alone.)
- **B — value-level semantic.** A dedicated labeler (the semantic agent one grain finer)
  persists `account_type-value → concept`, served downstream. A real artifact.
- **C — full DAT-620.** Proposer + binding table + teach + phase + measure-expr storage.

This lane builds **one probe, two legs (A and B), same fixture, reported separation
margin** — the ground-first kill gate — to decide which tier DAT-620 actually needs
before any plumbing is committed.

## The fixture + oracle (probe-local, synthetic, seeded)

A long-format finance table: `txn_id, posting_date, account_type, amount`. The
`account_type` discriminator carries **graded difficulty** classes, each with a known
concept (the oracle). Concepts/indicators taken from
`verticals/finance/ontology.yaml` (revenue / cost_of_goods_sold / operating_expense — the
P&L set sufficient for gross_margin):

| class | example value | oracle | what it tests |
|---|---|---|---|
| exact | `COGS`, `Sales Revenue` | by indicator | floor |
| synonym | `Turnover`→revenue, `Cost of Sales`→cogs, `SG&A`→opex | semantic, not literal | beyond string match |
| exclude-trap | `Cost Recovery Income`→revenue | contains `cost` (a revenue `exclude_pattern`) yet is revenue | exclude-pattern judgment |
| **novel** | `Direct Materials` | **unmapped** (not in confirmed set) | **fall-loud / no silent undercount** |
| explicit unmapped | `Suspense`, `Clearing` | unmapped | abstention |

**Oracle** = `concept → {column: account_type, values:[…]}` for each concept, plus the
`unmapped` set and a flagged `novel` value the labeler must **not** fold into a concept.

**Metric ground truth** = `gross_profit = Σ(revenue amounts) − Σ(cogs amounts)`,
`gross_margin = gross_profit / Σ revenue`, computed from the generated rows via the
oracle. If a leg's value-sets match the oracle, its reconstructed metric == ground truth.

**Seeds (DAT-450 convention):** vary which synonyms/novel values appear, amount
distributions, ordering. Disjoint `_FIT` / `_HOLDOUT` seed ranges; all scores **pooled
over holdout seeds** — never tuned to one dataset. Recall is separation/ordering, not a
tuned point threshold.

## The two legs (same inputs, compared cleanly)

Both legs get the **same** inputs: `top_values(account_type)` (value + count) computed
directly from the fixture (no pipeline) + the finance ontology concept list
(`name, description, indicators, exclude_patterns`, via
`analysis/semantic/ontology.py::format_concepts_for_prompt`). LLM constructed via
`dataraum.llm.providers.create_provider`.

- **Leg A (feed-only):** prompt = top_values + ontology → "assign each value to one
  concept or `unmapped`." Mimics what the graph agent would do inline if simply fed
  better context. No structured persistence, no teach.
- **Leg B (value-level semantic):** the dedicated labeler — same inputs in a
  semantic-agent-shaped contract (complete enumeration, explicit `unmapped`, per-value
  confidence; optionally fed driver `interesting_slices` as a hint). The "extend the
  semantic agent one grain finer" candidate.

Non-determinism handled by pooling over seeds/samples; **no deterministic overrides** of
the LLM's labels.

## Scoring (pooled over holdout seeds)

1. **Per-value precision/recall** vs oracle (multiclass; macro + per-concept).
2. **Trap metrics** (the decision-relevant ones): novel-value-correctly-unmapped rate;
   exclude-trap correctness.
3. **Metric-level error** (the outcome): reconstruct gross_profit / gross_margin from each
   leg's value-sets, report `|error|` vs ground truth.
4. **Separation:** B − A on each, relative/Goodhart-safe.

## Verdict rule → what each outcome triggers

- **A high (p/r at ceiling, novel correctly unmapped, metric error ≈ 0) and B no better**
  → no labeler to build. The fix is **DAT-616**: feed `top_values` + ontology into
  `graphs/context.py` + the blueprint prompt. **CUT** the proposer + binding table;
  record why. (Philipp's instinct confirmed.)
- **A fails the traps (silently folds `Direct Materials` → metric undercount) but B fixes
  it** → value-level labeling is load-bearing → **BUILD tier B** (extend the semantic
  agent to value grain). Whether persistence + teach are needed is the follow-up
  sub-question (does B need confirmation to be reliable on holdout?).
- **Neither clears the traps** → human teach/confirmation is required from the start →
  the binding table + teach earn their place → **BUILD tier C**. Record why.

## Build steps

1. `generate.py` — seeded long-format generator + oracle + metric ground truth.
2. `labeler.py` — legs A and B over `create_provider` + finance `OntologyLoader`.
3. `score.py` — p/r + trap + metric-error, pooled over `_HOLDOUT`, A-vs-B separation report.
4. Run; record the verdict (BUILD-tier or CUT-superstructure + why) in
   `entropy_eval_architecture.md`. If a tier survives, **graduate** the fixture into
   `vendor/dataraum-testdata` and the rig into `calibration/unit` (Tier 2) via
   `/evolve-testdata`.

## Deferred behind the verdict (do NOT build in lane 1)

- Full-pipeline (Tier 3) check that real profiling/drivers produce adequate labeler
  inputs (validates the "direct inputs" shortcut — Philipp's point #2).
- Binding table + form-a upsert + `current_*` view; `ConfigOverlay` teach applier; the
  begin_session phase wiring — only if B/C wins.
- The gross_margin/gross_profit metric-value **regression on the real pipeline**.

## Result — lane-1 verdict (2026-06-24, settled)

Two runs, Sonnet-4.6, 6 holdout seeds pooled, legs A (feed-only) vs B (value-level
semantic contract), same inputs.

**Clean fixture (semantic names):** both legs ≈ perfect; **`gross_profit rel.err = 0.000`**
for both. Synonyms (`Turnover`, `SG&A`), the exclude-trap (`Cost Recovery Income`→revenue
despite "cost"), exact, non-P&L all 1.000. The only A-vs-B gap was abstention on genuinely
unmappable values (A force-fit ~11%), and it did **not** touch the metric.

**Hard fixture (opaque GL codes `4000/5000/6000`, abbrevs, ambiguity):** codes are the
wall — accuracy A **0.00** / B **0.22** — and the failure is **dangerous, not safe**: on
codes A mislabels **100%** (never abstains), B still mislabels **61%**. The LLM does not
recognize "I can't ground this"; it commits to a wrong concept. Reconstructed gross margin
comes out **57–81% wrong**, and the better prompt (B) does not fix it (it's worse on the
metric). Abbrevs/ambiguity/exact/unmapped stay clean.

**Verdict:**
- **BUILD — DAT-616 (feed `top_values` + ontology).** Sufficient and exact for semantic
  names; the "agent improvises and gets revenue wrong" premise does not reproduce once fed.
- **CUT — the standalone lexicon-proposer + binding superstructure as the *primary*
  grounding mechanism.** A lexicon-over-`top_values` LLM does not solve codes (no signal in
  the discriminator) and is not needed for names. (Driver/amount evidence was withheld by
  design; per Philipp it is not pursued — see next.)
- **KEEP, scoped to codes/unmappables — teach (human authority).** Codes are a **teach
  case by design**: expecting the system to know a user's account numbers is unreasonable;
  a missing chart-of-accounts mapping is human error. The binding table + teach rail is
  justified as the *teach target*, not as a guess-the-code proposer. (Future: discover
  common COA formats as an interpretation-limited heuristic, never as ground truth.)
- **MANDATORY — fall-loud / grounding-confidence floor.** Because the LLM mislabels codes
  *confidently*, the system must mark the metric inconclusive-with-reason rather than emit
  a 57–81%-wrong number. This probe is the empirical case for the DAT-616 sanity floor +
  the binding's fall-loud.

Rig kept (not deleted): its long-format fixture + concept oracle is the seed the handoff
asks eval to own, and the teach-path + fall-loud are now the things to gate.

## Open risks / first unknowns

- **LLM provider wiring in a probe** — no precedent in `scripts/probes` or `calibration`.
  Entrypoint is `dataraum.llm.providers.create_provider(provider_name, provider_config)`
  + a credentials provider (`core/credentials.py::EnvProvider`). Resolve this first; it's
  the only non-obvious wiring.
- **Ontology coverage** — revenue/cogs/opex/depreciation/interest/tax cover the P&L;
  gross_margin needs only revenue + cogs, so coverage is sufficient for lane 1.
