# RFC verification — the drafts against the code

*Audit of the RFC 0–4 drafts (`_source/`) against the three repos as they stand on
2026-07-27. Every verdict cites a file, a ticket, or an explicit empty grep. The
golden RFCs in this directory are the result; this document is the evidence trail
behind their edits, kept so the edits are not re-litigated from memory.*

Repos read: `dataraum-eval` @ `ee43f0f`, `vendor/dataraum-context` @ `bce2256ab`,
`vendor/dataraum-testdata` @ `a7c57ad`. Jira read live (DAT project).

---

## Summary of the audit

The **concept model is sound and mostly already implemented in spirit**. The
**sequencing is not executable as written**, for four reasons that compound:

1. The grammar the RFCs assume (`entity × metric-per-unit × comparison`) is not
   expressible in the engine's metric DAG today. Two of its three terms are missing
   or broken.
2. The one product claim RFC 1 leads with — "a deviation is only surfaced when it
   exceeds the target's own uncertainty" — needs an error term for the *recovery
   pipeline* that has never been measured, and the ticket that would measure it
   (DAT-687) is not started.
3. The sequencing is driven by **external data availability**, which is the wrong
   binding constraint. The real ones are: one vertical per workspace (a born-loud
   engine guard), a finance-monolith generator with no dispatch seam, and an
   ungraded answer path.
4. Both RFC 3 variants sequence *around* the iteration currently being closed
   (DAT-680 / DAT-869 / DAT-671) instead of *through* it. DAT-671 is the granularity
   ladder. DAT-879 is the axis catalog it needs. Those are the first two rungs of
   RFC 0, already in flight, and the drafts don't mention them.

Nothing here argues against the six dimensions. It argues that four of the six
cannot be graded, three of the six cannot be generated, and the two that can are
gated on grammar work the RFCs assume is done.

---

## RFC 0 — concept model

| Claim | Verdict | Evidence |
| :---- | :---- | :---- |
| "The finance ontology in the box *is* a predefined domain ontology bound to discovered data with measured confidence" | **Supported** | `packages/dataraum-config/verticals/finance/ontology.yaml` (25 concepts, indicators, `conventions`, `compositions`); typed vocabulary in `analysis/semantic/db_models.py:37` (`ConceptKind`), `:156` (`Concept`), `:100` (`ConceptEdgePredicate` — `part_of` / `disjoint_with` / `reconciles_with`) |
| "This does not introduce a new mechanism; it generalizes a proven one" | **Half true — and the unproven half is the half that gets multiplied by six** | Concept→column binding *is* proven: the roles oracle grades 8/8 business-concept bindings, 10/10 measure roles, on the finance corpus. Concept→**SQL** grounding is not: **DAT-709** (open) — `current_assets` and `current_liabilities` ground to the *identical* extract, so `current_ratio ≡ 1.0`. ADR-0016 is explicit that the deterministic metric-SQL builder was abandoned and the LLM authors metric SQL; the verifier is "a cheap post-execution sanity floor only" |
| "Priors propose, never suppress" | **Supported as a design rule, unenforced as a mechanism** | Matches ADR-0009 (entropy as disagreement) and the project's standing rule against deterministic overrides of LLM judgments. There is no test that a prior cannot outrank recovered structure — that is a new eval oracle, not an existing guarantee |
| Granularity ladder | **Supported, and already in flight** | `og_rolls_up_to` + `og_period_rolls_up_to` (`storage/property_graph.py:927,971`); `dimension_hierarchies` phase (`pipeline.yaml:92`); **DAT-671** is the drill-down epic (in progress), **DAT-879** the axis catalog it is blocked on. The RFC describes work that is half-built |
| Unit-economics grammar: `entity × metric-per-unit × comparison` | **Unsupported — two of three terms are missing** | *metric-per-unit*: `StepType` is `extract / constant / formula` only (`graphs/models.py:31`); **DAT-838** (open) — extract steps carry no predicate, so "revenue **for segment B**" is unsayable; metric grain is `scalar / series / table` (`:39`) with no per-entity declaration. *comparison*: no target of any kind exists (see RFC 1 below) |
| Coverage map (lit / partial / dark) | **Not built; every input exists** | Grounding edges (`og_grounding`, `og_grounded_by`), readiness bands (`entropy/loss.yaml:27`, `low_upper 0.3 / medium_upper 0.6`), additivity verdicts (`og_additivity`), temporal coverage (`og_temporal_coverage`). This is a read over existing rows, not new measurement — the cheapest high-value item in the whole RFC set |
| Allocation as an explicit, versioned, inspectable rule | **Absent** | `grep -rniE "allocat" packages/engine/src/dataraum` → **zero hits**. Not "partially built" — the concept does not exist in the engine |
| Compliance by design (Throughput, person-level quarantine) | **Understated as a schema convention; it is a missing capability** | The engine binds *discovered* columns. There is no PII/person typing, no quarantine path for a person-grained binding, and nothing in the ontology expresses "never bind at this grain". Real partner data will contain `worker_id`; today it would be bound like any other dimension |
| Archetypes weight, never filter | **No surface** | No archetype field anywhere. The declaration point would be the cockpit `frame` stage (`src/routes/create.tsx`, `tools/frame-family.ts`). Cheap to add, but it weights nothing until the coverage map exists |

### The vertical question, answered from the code

RFC 0 leaves it implicit; it needs an explicit ruling because it changes the data model.

**A performance dimension is not a vertical, and must not become one.**

- A vertical resolves to exactly one of `shipped / framed / placeholder / unknown`
  (`core/vertical.py`) and is a *vocabulary pack*: concepts, metrics, cycles,
  validations, conventions.
- **A workspace carries exactly one.** `worker/workflows.py:127 _single_vertical`
  raises on `len(verticals) > 1`: *"multi-vertical grounding not yet supported … a
  workspace must carry exactly one vertical until ontology merge lands."* The wire
  carries a list for forward-compat; the engine refuses it.
- So "one dimension = one vertical" means six workspaces per company. That breaks the
  RFC's own competitive claim: the cross-dimension compound queries (Supply × Capital,
  Demand × Capital) are single queries only inside one grounded model. Across
  workspaces they are not expressible at all — separate schemas, separate graphs,
  separate enriched views.
- It would also fragment the eval axis: `calibration/cube.py` declares `vertical` per
  oracle, so six verticals means six incomparable scoreboards for one company.

**The grounded model:** `dimension` is a **facet on concepts and metrics inside a
vertical's ontology**. The vertical stays the industry vocabulary (finance,
motorsport, a partner's ERP dialect). Cross-dimension comparison then happens where it
already has a substrate — the conformed-dimension / bus-matrix surface
(`og_conformed_dimension`, consumer pending in **DAT-809**) — not by merging verticals.

Sequencing note: the facet lands on the same ontology parse surface that **DAT-883**
(envelope re-parse) and **DAT-724** (entity taxonomy) touch. DAT-869 already records
the constraint — *"Sequence them; do not run both."* The dimension facet is a third
rider on that same surface and belongs in that sequence.

---

## RFC 1 — forecast targets and the what-if operator

| Claim | Verdict | Evidence |
| :---- | :---- | :---- |
| "Nothing in the grammar predicts / answers what-if" | **Correct, and stronger than stated** | `grep -rniE "forecast\|what.?if\|scenario" --include=*.py` over the engine → **zero hits**. Not thin — absent |
| Plan / prior-period / internal-peer as target sources | **None exist** | No plan vertex or edge among the 26 `og_*` element views (`storage/property_graph.py:175-201`). No peer-comparison code. `tolerance` exists only as a validation-check parameter (`analysis/validation/evaluate.py`, `deviation <= tolerance`), which is a data-integrity check, not a performance target |
| "Every target carries a model, an interval and an evidence grade" | **Sound, and already partly decided elsewhere** | **DAT-749** (epic, active) is the decided mechanism: TabICL as the forecaster, **CQR over a monthly-growing calibration set** as the interval (gate resolved 2026-07-14, ACI rejected, re-gate trigger recorded at h≥3), support-boundary guard mandatory, what-if = **explicit lever conditioning, never the forecaster alone** (DAT-752). RFC 1 re-opens as an "open question" what the project already ruled on |
| "A −4% against a ±9% band is not a finding" — deviation significance as the product | **The claim is currently unsupportable, for a reason the RFC does not name** | The band must cover *both* error terms. The pivot's own contract is `pipeline error + model error ≤ decision tolerance` (DAT-680 description). Model error = the conformal band (planned, DAT-750). **Pipeline error — the error the model *recovery* introduces — has never been measured.** `calibration/outcomes.py` grades *eval-authored golden SQL* against generator truth, explicitly not the engine's own SQL; **DAT-687** ("grade the product answer path") is the ticket that would produce the term and is To Do |
| Entity birth and death | **Correctly identified; no substrate** | `og_temporal_coverage` gives per-entity time extent, which is the raw material. Nothing consumes it for this |
| Typed levers, no path → no simulation | **Sound and consistent with DAT-752's support-boundary guard** | The "no path, no simulation" rule maps onto the property graph cleanly — refuse when no `og_*` path connects lever to metric. That is a real, cheap guard once levers exist |
| "Allocation is the substrate for propagation" | **Correct, and it makes allocation a Stage-0 dependency of what-if, not a provenance nicety** | Same empty grep as RFC 0 |

**The sequencing inversion this implies.** RFC 3 ships forecast first because it
"lights every partial branch without a new data source". But of the four estimators,
forecast is the only one needing a new runtime (torch worker, calibration set,
backtests), while **prior period and internal peer are pure SQL over the existing
metric graph, `og_temporal_coverage` and the slice catalog**. The differentiating UX
line — *"here is which target we used and why not the others"* — is delivered by the
**operator**, not by the forecast. Build the operator with the two cheap estimators
first; forecast then plugs into the same slot as a third. This is a genuine
disagreement with the draft and it follows from the draft's own unification argument.

---

## RFC 2 — dimension specifications

Two variants exist. `_1` supersedes the original on data availability (it revises
Supply from "the gap" to "strong" and Capacity from "very weak" to "strong") and adds
the licence column. The golden copy takes `_1` as the base.

| Claim | Verdict | Evidence |
| :---- | :---- | :---- |
| Canonical entities / ladders / unit metrics per dimension | **Reasonable as a spec; not gradeable** | The generator (`vendor/dataraum-testdata/src/testdata/canonical/finance/models.py`) emits: `ChartOfAccounts`, `JournalEntry`, `JournalLine`, `Invoice`, `Payment`, `BankTransaction`, `FXRate`, `TrialBalance`, `BalanceSheet`, plus probe skeletons (`MeasureProbe`, `FormulaProbe`, `RefEntity`, `RefActivity`, `Address`, `Order`, `Delivery`). **There is no customer, no product, no supplier master, no quantity, no unit of measure, no inventory position, no asset, no work order.** `Invoice.vendor_id` is a bare string with no vendor table; `Order`/`Delivery` are empty skeletons for the role-playing-FK probe with no money on them |
| Capital "moderate / more buildable than Capacity or Throughput" | **Half-shipped already, and un-grounded** | `verticals/finance/metrics/working_capital/` ships `dso`, `dio`, `dpo`, `cash_conversion_cycle`. On our own corpus: no inventory table → DIO has nothing to ground; invoices are **vendor-side** (`vendor_id`) → the AR half of DSO does not exist. So the shipped Capital templates are the *existing* live example of a dimension going dark, which is a useful demo and a real defect at once |
| Demand "strong — rel-salt is real SAP sales data" (original) vs "**rel-salt is CC-BY-NC-SA, cannot carry a commercial demo**" (`_1`) | **`_1` is right and matches our own policy** | `entropy_eval_architecture.md` §License tiering already rules NC corpora internal-use-only, fetched at run time, never committed. `corpora/relbench/rel-salt` is on disk (85 MB) under exactly that rule |
| Supply "no longer the gap" — BPI 2019, AdventureWorks `RejectedQty`, SCMS/openFDA | **Unverifiable from this repo** | On disk: `corpora/relbench/` (rel-avito, rel-event, rel-f1, rel-hm, rel-salt, rel-stack, rel-trial) and `corpora/rwd/`. No AdventureWorks, no BPI, no SCMS, no Cincinnati. Every row count, licence and column claim in `_1` is an external assertion this audit cannot confirm or refute |
| Capacity "strong — Cincinnati Fleet Services, every metric a literal column" | **Unverifiable from this repo; and it collides with the corpus contract** | Same as above. Additionally: a public fleet dataset is **Tier B** — structural truth only, no injections, no recall. It can falsify "we're great"; it cannot certify a Capacity metric is computed correctly, because nobody knows the true answer. The `_1` sequencing treats these corpora as if they conferred correctness evidence; under our own two-tier policy they do not |
| Cross-dimension compound queries as the competitive point | **Agreed, and the substrate is named** | `og_conformed_dimension` + the bus matrix are exactly the "one allocation scheme spans both" mechanism; **DAT-809** wires the first consumer. Worth stating in the RFC, because it converts a positioning claim into a build item |

---

## RFC 3 — sequencing

| Claim | Verdict | Evidence |
| :---- | :---- | :---- |
| "The constraint that shapes this is data availability" (original) / "licence and cross-dimension coherence" (`_1`) | **Both wrong about the binding constraint** | The binding constraints are internal: (a) one vertical per workspace, born-loud (`worker/workflows.py:127`); (b) the generator is a compile-time finance monolith with no dispatch seam — the DAT-680 re-scope verified "6 hotspots, a fork not a plugin", and **DAT-689 (the vertical protocol) is Cancelled**; (c) the answer path is ungraded (**DAT-687**, To Do); (d) extracts have no predicate (**DAT-838**) |
| Stage 1 — "forecast targets applied to the finance ontology that already ships … lights every *partial* branch without a single new data source" | **False twice over** | (i) The shipped finance ontology is a **reporting** ontology (EBITDA, margins, DSO/DIO/DPO, current ratio) and the pivot retired reporting as a target — DAT-680: *"financial reporting is no longer a target … reporting artifacts become generator-internal consistency checks, not graded deliverables"*. Stage 1 as written ships forecasts on top of the demoted catalog. (ii) Several of those branches are not *partial*, they are **broken or ungroundable** on our own corpus: DAT-709, no inventory, no AR |
| Stage 2 — Demand + Offer together | **Right call, wrong reason** | The draft's reason is public-data availability. The grounded reason is better: Demand+Offer is the **cheapest extension of the generator that produces new truth**, it is where the DB ladder lives, and it repairs the missing AR side that currently makes DSO ungroundable. Keep the stage; restate the justification |
| Stage 3/4 reorder (Supply and Capacity moved up on new data) | **Not executable** | Neither dimension has a generator, and Tier-B corpora confer no correctness evidence (above). Moving them up on the strength of unverified public datasets swaps a data argument for a data argument and skips the two internal blockers |
| "Ship one dimension at a time and let the coverage map carry the roadmap story" | **The single best line in the draft** | And it is nearly free — the coverage map is a read over rows that already exist. It should be promoted from a narrative device to an early deliverable, with a hard gate: a dimension may only read *lit* if one of its unit metrics grounds **and** grades |
| Data work items table | **Mostly sound; two additions missing** | The backtesting harness and the licence audit are right. Missing: the **pipeline-error measurement** (DAT-687) and the **generator extension** that gives any dimension truth. Also: the "binding regression suite / MMTU" item duplicates a capability we already own — `calibration/cube.py` + `metadata_truth.yaml` + 27 graded oracles. Extend that; do not import a second harness (MMTU is Backlog under DAT-680 for exactly this reason) |
| Neither variant mentions DAT-680 / DAT-869 / DAT-671 | **The main structural gap** | DAT-671 *is* the granularity ladder; DAT-879 *is* the axis catalog; DAT-857/DAT-868 are the per-axis additivity verdicts that decide whether a roll-up on the ladder is even legal. A roadmap that starts at "Stage 1" without them re-plans work that is in flight |

---

## RFC 4 — demo and reference data

| Claim | Verdict | Evidence |
| :---- | :---- | :---- |
| "Demo" is four jobs (first meeting / proof of fit / engineering fixtures / marketing) | **Strong, and it maps onto our existing tiers** | Job C is Tier A + Tier B in `entropy_eval_architecture.md`. Jobs A and D are a corpus we do not have. Naming them separately is the right move |
| What we extract from a partner is **shape**, not rows | **Sound, and it has a precedent in the repo** | `schema_transforms.py` (normalization levels, column styles, key strategies) is exactly a shape-parameter layer, already used to vary the synthetic corpus |
| Rights ladder (four grantable levels) + publication-review window | **Sound. Commercial, not technical — outside this audit** | — |
| Tier 0 / Tier 1 / Tier 2 tiering | **Conflicts with the corpus policy as written, and is reconcilable** | Our policy has two tiers: A = synthetic with full truth (the only place recall is assertable), B = wild with structural truth only, never a build gate. RFC 4's "Tier 1 structure-preserving synthesis" is *not* a third tier — it is Tier A with borrowed shape parameters, which the policy already blesses: *"any future vertical replicates a **documented real backend system** with synthetic values generated into the borrowed schema, so ground truth stays computable"* |
| The reference company as a **stitch** of five open corpora | **This is the one design decision to change** | A stitched dataset of real rows from five sources has **no ground truth**: you cannot state the true DB2 of a fictional firm assembled from someone else's rows, so the reference company can serve jobs A and D but never job C, and can never grade a dimension. **Generating into the borrowed AdventureWorks schema** yields both: the schema realism the policy asks for *and* computable truth. Same spine, same vocabulary, same demo — with an answer key |
| "No unlabelled synthetic figure ever appears in a demo" + provenance ledger rendered in the product's own surface | **Keep verbatim.** It is the strongest idea in the document | And it is buildable on the readiness/provenance surfaces that exist |
| "Why the AI-training-data boom did not solve this" | **Correct in substance** | Consistent with what the corpus survey found: multi-table operating data with money and a time axis is not published. Our own Tier-B shelf is 7 RelBench databases plus one FD-truth corpus |

---

## Corrections to this audit's first pass (2026-07-27, same day)

Four findings in the first pass were wrong or incomplete. Recorded rather than quietly
edited, because two of them would have pointed the roadmap the wrong way.

1. **Retracted: "do not invent a second synthetic vertical."** This imported a *test-team*
   rule about corpus bias (`entropy_eval_architecture.md`; DAT-690/691 cancelled) into a
   *product* roadmap, where it reads as "stay in finance" — the opposite of the pivot. The
   rule's defensible core is narrower: **borrow schema shapes from documented real systems,
   and keep the wild tier as the counterweight.** Bias is managed by checking the shape
   against something real, not by refusing to generate new domains. The generator's domain
   follows the product's.
2. **The generator was treated as a constraint; it is a lever.** The first pass let "the
   generator is a ledger" drive the sequencing. It is our code, costs no tokens, no partner
   and no licence, and it has *already* been extended for exactly this class of work:
   `Lever(period_k, factor, type="price_level")` is a DGP intervention producing an **exact
   same-seed counterfactual** with `intervention.yaml` beside the data
   (`canonical/finance/generators.py:289`, `scenarios/runner.py:321`, test in
   `tests/test_generators.py`). What-if ground truth exists today. Generator work is now
   lane A of RFC 3 and starts immediately.
3. **The facet ruling was right but incomplete — it did not answer the inference question.**
   The pipeline works because a *narrow* vocabulary maps onto selected data. The missing
   argument: a facet **classifies** the customer's framed model rather than enlarging it
   (the prior library lives at frame time, pruned by induce/declare), narrowness at
   inference is preserved by data scoping + archetype weighting + table-local scoping, and
   inference *between* facets runs on three typed carriers — concept edges, verified
   topology, conformed dimensions — never on name similarity (DAT-723 is the live instance
   of what name-similarity inference costs). RFC 0 now carries this in full.
4. **The cockpit was missing entirely, and it is where the dimensions land.** Read since:
   `frame` induces the whole model — concepts, validations, cycles, metrics — over a staging
   schema, seeded with structural few-shot from the nearest shipped vertical, *except*
   validations, because (DAT-725 band 3) a finance few-shot **is** finance vocabulary and
   leaks across verticals. **The six dimensions are the vertical-neutral seed library that
   leak proves is missing** — the highest-leverage placement in the program, and it needs no
   new surface. Also missed: recipes (backend + named SELECTs, authored in the staging hub)
   as the acquisition point a dimension prior can propose; the `answer` sub-agent, which
   already carries a data-quality band as *information, never a filter* — the seam the target
   disclosure rides; and DAT-855, whose three strands (**answer agent → root-causing**,
   **frame induction acquiring metrics**, **"defining a vertical as an ontology graph"**) are
   this RFC set's delivery, already scheduled as Phase 4 of the locked program. New
   [`rfc_6_product_surfaces.md`](rfc_6_product_surfaces.md).

5. **`tfm/` was dismissed as a research subproject; it is the predictive half's evidence
   base.** (The dead-code appendix of the framework review lists it as unwired — true of the
   *harness*, misleading about the *findings*.) Measured: TabPFN-TS-3 is calibrated out of
   the box (0.816@80, 0.965@95) but **non-commercial**, while TabICL is BSD-3 and needs CQR
   — which is why DAT-750 resolved as it did. No forecaster tracks a regime change even six
   months in (0.27–0.69 effect recovered), so lever conditioning is a *measured* requirement.
   In-support what-if recovers a held-out effect at **1.011**; out-of-support TabICL widens
   17–24× and stays honest while TabPFN covers **0%** — the support guard is engine-specific.
   Scenario row generation was CUT at a 3.8-second fidelity gate. Consequence for
   sequencing: **prediction is not the long pole**; it is waiting on a metric worth
   forecasting.

## The five corrections that change the plan

1. **A dimension is a facet, not a vertical.** One vertical per workspace is enforced
   in code. Cross-dimension queries — the differentiator — only exist inside one
   grounded model. (RFC 0, new section; RFC 3 ordering.)
2. **The grammar is a prerequisite, not an assumption (RFC 3, lane B1).** Extract predicates (DAT-838),
   grounding disambiguation (DAT-709), and per-axis additivity (DAT-857/868) are the
   prerequisites of *any* unit metric. They are already ticketed and partly in flight.
3. **Measure the pipeline error before selling deviation significance.** DAT-687 is
   promoted from "the biggest remaining eval hole" to the gate on RFC 1. Without it
   the honest band is unknown, and an unknown band cannot decide what is a finding.
4. **Targets before forecasts.** Prior-period and peer are SQL; forecast is a runtime.
   The product line is the operator's disclosure, not the model.
5. **The reference company is generated into a borrowed schema, not stitched from wild
   rows.** That is the only version that can carry demo *and* fixtures. Borrowing is about
   the provenance of the *shape*; where no documented schema fits, designing one is
   legitimate provided it is checked against something real.
6. **The program is two lanes, not one chain.** Everything in our own repos — the
   operating-model generator, the prior library, the pipeline-error measurement,
   comparability — starts now and needs nothing from the engine. The engine half plugs into
   Phase 4 of the locked stabilisation program, which is already where this work was
   scheduled. The correctness gates bind *claims* ("this deviation is significant", "this
   dimension is lit"), never the build.

## What this audit could not check

Every external dataset claim in RFC 2 `_1` — row counts, column presence, licences,
measured OTD rates. None of those corpora are on disk here. RFC 3 `_1` re-sequences
the entire roadmap on them, which makes the **licence-and-content audit a blocking
prerequisite of that sequencing**, not a small parallel chore. The golden RFC 3 treats
them as *unverified inputs* and does not let them move a stage.

---

## Second pass — independent re-grounding of the golden set (2026-07-27)

A fresh review re-verified the golden RFCs' load-bearing claims against the code
(engine, testdata, cockpit) and the live ticket set, independently of the first pass.
Most held; the deltas below were folded into the golden copies the same day.

**Confirmed as written:** one-vertical-per-workspace is enforced at four independent
layers (workflow guard, concept-store bind, SQL read surface, cockpit registry column);
the comparison term is absent everywhere (engine + cockpit, drill included — slicing,
pinning, time-bucketing only, no period-over-period); the coverage-map inputs all exist
as rows; allocation is grep-empty.

**Corrections folded in:**

1. **Frame-seed leak, scope and cost** (RFC 6): the leak is 2/3 families by explicit
   ruling (validations de-seeded under DAT-725 band 3), and the seed reader is an
   injectable parameter (`frame-family.ts` — `nearestSeedVertical` / `readSeed`), so the
   prior swap is a parameter change plus content, not a rewrite. B3 is cheaper than the
   first pass implied.
2. **"Recipe" naming** (RFC 6): no user-facing recipe surface exists — only the internal
   DB-source connection loader (`sources/db_recipe/`). Starter recipes are new authored
   content feeding an existing mechanism.
3. **No forecast seam exists at all** (RFC 1): zero forecast/what-if/scenario code in the
   engine or its git history; no torch; DAT-750's resolved gate settled the CQR *decision*,
   not a build. `simulate` lives only in a vision doc. (The first pass said "absent" of the
   grammar; this extends it to the runtime — nothing is sunk by parking forecast.)
4. **The counterfactual capability is narrower than the mechanism** (RFC 1): one lever
   type (`price_level`), Python-API only, no `units × price` decomposition; exactness
   rests on scale-after-every-draw with no value-branching. Design constraint recorded for
   A1: stable-entity-id-keyed RNG streams (DAT-884).
5. **Extract predicates exist one layer down** (RFC 0/3 context): `sql_snippets.parts`
   carries typed where-clauses and `ConceptGroundingBasis.filter_members` records
   dimension-member filters as provenance — DAT-838 is a declaration-side gap, which
   supports its "small" sizing.
6. **New material — the run-model artifact split** (RFC 3 open questions): 28 tables carry
   `run_id` + HEAD (measurement layer), 15 do not (model layer, `superseded_at`-versioned);
   validation verdicts are never stored (ADR-0017). Ruling recorded: no run-per-dimension
   now; the facet coordinate gives per-dimension reads; incremental-adoption economy
   belongs to the cache lane (DAT-861); the head-target string stays extensible.

**Decisions taken 2026-07-27** (Philipp, verbatim; recorded in Jira the same day):

- DAT-687 green-lit — **"ok"** (comment on DAT-687; the 2026-07-21 hold released).
- A1 = extend the existing corpus in place into reference company v0 — **"yes, also my
  understanding"** (DAT-884; RFC 3/4 updated).
- Forecast out of the near-term roadmap — **"yes, forecast is out"** (comment on DAT-749;
  DAT-750/751 + backtest harness parked; RFC 1/3 updated).

**Tickets minted:** DAT-884 (A1, parent DAT-680), DAT-885 (A2 thin — Demand/Offer/Capital,
parent DAT-680). A4's four extensions scoped onto DAT-862 by comment. Program state note:
DAT-853 reads To Do in Jira but is recorded closed via PR #537; DAT-725 is Done — Phase 3
(DAT-671 + DAT-869 slice catalog) is the live phase.
