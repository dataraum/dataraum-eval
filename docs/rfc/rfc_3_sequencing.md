# RFC 3 — Sequencing

*Status: golden (re-sequenced against the code, the locked program and the live ticket set, 2026-07-27) · Part 3 of 6*
*Highest churn of the set; kept separate so RFC 0 stops moving. Evidence: [`rfc_verification.md`](rfc_verification.md)*

---

## The shape of this plan

The performance-analytics move is **not** a new program waiting for a slot. It is already
the last phase of the locked stabilisation program, and its three strands are this RFC:

| Phase | Package | Relation to the dimensions |
| :---- | :---- | :---- |
| 1 | **DAT-853** wild-corpus harvest — instruments, abstention contract, catalog invariants | fixes the gauges everything else is measured with |
| 2 | **DAT-725 finish** — P5 → P6 units → P7 → P8/P10 → P11 | the operating-model graph the facets attach to |
| 3 | **DAT-671 + P12** — drill UX; bus matrix + cross-fact drill-across | **the granularity ladder and the cross-dimension join** |
| 4 | **DAT-855 direction work** — (1) answer agent → root-causing, (2) frame induction acquiring validations/cycles/metrics, (3) **"defining a vertical as an ontology graph"** | **this is the dimension model's delivery, already scheduled** |

So the sequencing question is not "when do we start" but "what do we put into Phase 4, and
what can run in parallel before it". The answer to the second half is: **a lot, and it is
all in our own repos.**

Two lanes, running concurrently:

- **Lane A — ours (`dataraum-eval` + `dataraum-testdata`).** No engine dependency, no
  stabilisation-program dependency, starts now. It produces the thing every later claim
  needs: **data with an answer key, and a measured error on our own numbers.**
- **Lane B — engine + cockpit.** Rides the program: Phase 3 finishes the ladder, Phase 4
  lands the facet, the priors, the target operator and the coverage map.

## Decisions already taken

| Decision | Resolution |
| :---- | :---- |
| Dimension count | Six: Demand, Offer, Supply, Capacity, Throughput, Capital |
| Industry handling | Archetypes weight the dimensions; they never filter them. Vertical vocabulary parameterizes within a dimension |
| Allocation schemes | Named, plural, comparable side by side. Not one hidden scheme |
| Prior strength | Priors propose, never suppress |
| Target operator | Evidence-ranked, not availability-ranked; every target carries a model, an interval and an evidence grade |
| What-if | The inverse of the existing grammar; typed levers; explicit lever conditioning, never the forecaster alone (measured — RFC 1) |
| **Dimension = facet, not vertical** | A typed facet on concepts and metrics. It *classifies* the customer's framed model rather than enlarging it; narrowness is preserved by data scoping, archetype weighting and table-local scoping (RFC 0) |
| **Operator before forecast** | Prior-period and peer are SQL over existing substrate; forecast is a new runtime. The product line is the operator's disclosure |
| **Bands cover two error terms** | `pipeline error + model error ≤ decision tolerance`. The claim waits on the measurement; the build does not |
| **The generator is a design surface** | Extending it is the only thing that turns a dimension from demoable into gradeable, and it is entirely ours (RFC 2) |
| **The priors' home is frame induction** | Where they also replace a seed known to leak one industry's vocabulary into another's (RFC 6) |
| **Forecast is out of the near-term roadmap** (2026-07-27, "yes, forecast is out") | DAT-750/751 parked until a customer asks; the operator ships with prior-period + peer + standard; the engine has zero forecast code, so nothing is sunk; `tfm/` stays the standing gate. Recorded on DAT-749 |
| **DAT-687 green-lit** (2026-07-27, "ok") | The 2026-07-21 hold is released — Phase 2 landed the substrate (`sql_snippets` DAT-646, validation `sql_used` DAT-617). Recorded on DAT-687 |
| **A1 = the existing corpus extended in place** (2026-07-27, "yes, also my understanding") | Reference company v0 is the finance corpus grown an operating chain — one corpus for ledger truth, operating truth, demo and fixtures; not a second corpus. DAT-884 |

## What actually constrains the order

Not public-data availability, and not licence. Four internal facts:

1. **The grammar is incomplete.** Extracts carry no predicate (DAT-838), so "revenue for
   segment B" — the shape of every unit metric — cannot be declared. Metric grain has no
   per-entity form. Per-axis additivity verdicts are unbuilt (DAT-857/868).
2. **Grounding disambiguation is broken in a way that scales with the prior surface.**
   DAT-709: two concepts ground to the identical extract, so `current_ratio ≡ 1.0`.
3. **Nothing grades the numbers the product computes.** The deliverable scoreboard runs
   eval-authored golden SQL; DAT-687 grades the engine's own and is not started.
4. **Only half of one dimension can be generated with truth.** The generator is a ledger.
   This is the constraint that is *fastest to remove*, and removing it is Lane A.

Note what is *not* on that list: the predictive half. Forecasting is measured and
calibrated, in-support what-if passed its gate, and what-if ground truth already exists as
an exact same-seed counterfactual (RFC 1). **Prediction is not the long pole — it is
waiting on a metric worth forecasting.**

---

# Lane A — starts now, in our repos

Nothing here needs the engine to change, and every item raises what the engine work can
later claim.

### A1 — The operating-model generator

**Ticketed: DAT-884 (2026-07-27), with the shape decided — extend the existing finance
corpus in place**, so reference company v0 is one corpus carrying ledger truth, operating
truth, demo and fixtures at once. Revenue entries derive from order lines (`units ×
price`) and feed the existing GL cascade, which fixes the missing AR side and keeps the
ledger oracles valid. Named design constraint from the grounding read: same-seed
counterfactuals must survive the rebuild — key RNG streams by stable entity ids, not draw
order (RFC 1). Named follow-up cost: a 3-seed clean-band re-baseline.

Extend the generator from a ledger to an operating model, events-first, truth exported with
the entities:

- **customer → order → order line → shipment → invoice → receipt**, with quantities, prices
  and a product hierarchy with standard cost. This one chain yields Demand, Offer, the AR
  half of Capital, and a true DB1 per customer and per product group.
- Then, per dimension as it comes up the roadmap: vendor/PO/goods-receipt (Supply),
  asset/meter/downtime/maintenance-order (Capacity), work-order/operation/scrap
  (Throughput), inventory positions (Capital).
- **Levers as DGP parameters**, following the price-level precedent: same-seed exact
  counterfactuals with `intervention.yaml`, one per lever type in RFC 1's table.
- Borrow schema *shapes* from documented real systems where possible — it buys realism and
  it is the standing rule for new domains. Borrowing is about provenance of shape, not
  permission to generate.

**Exit:** a scenario emits an operating-model corpus with `ground_truth.yaml` covering DB1
per customer and per product group, and at least one lever pair.

### A2 — The dimension prior library

**Ticketed: DAT-885 (2026-07-27), thinned to three dimensions first** — Demand, Offer,
Capital, the three the A1 chain lights — structured as a selectable per-dimension menu,
because that is the cockpit flow it serves (select metrics at frame time → recipes follow
from the selection; selection-first is itself the noise control). Supply, Capacity and
Throughput priors wait for their generator families.

Six priors as data, not code: canonical entities, ladders, unit-metric templates, expected
relations, typed `dimension` facet values. Authored vertical-neutrally (that is the whole
point — they are the cross-industry spine, unlike the finance seed they replace).

Deliverable shape: the seed library that frame induction reads (Lane B), the starter
recipes the staging hub proposes (RFC 6), and the vocabulary the coverage map groups by.

**Exit:** the library exists as declarations, and a dry-run over the A1 corpus and over one
wild corpus shows which dimensions each schema *could* carry.

### A3 — The pipeline-error measurement (DAT-687)

**Green-lit 2026-07-27** — the 2026-07-21 hold is released; Phase 2 landed the substrate
(per-metric SQL in `sql_snippets`, validation `sql_used` persisted). Runs after A4's small
store extensions, before/alongside A1. Expected first mechanical catch: DAT-709.

Grade the product's own answer path — metric-graph SQL and validation verdicts — against
generator truth, at KPI tolerance rather than reporting exactness. This is the number that
makes every band in RFC 1 honest, and it is eval-side work.

**Exit:** a pipeline-error distribution on at least one graded unit metric, recorded with
its value in the verdict store.

### A4 — Comparability

The four extensions in RFC 5: verdicts carry values not just statuses; wild runs write to
the same store; `dimension` becomes a cube coordinate; reducer variance is reported. Small,
and it is what makes "did the DB1 error move?" a query.

**Exit:** the store answers a per-dimension, per-dataset, per-vertical trend question
without a re-run.

---

# Lane B — engine and cockpit, on the program

### B1 (Phase 3, in flight) — Finish the ladder

DAT-671 lane 1 (DAT-714 → DAT-673 remainder → DAT-678 → DAT-676 → DAT-627), the axis
catalog DAT-879, and lane 2's bus matrix + cross-fact drill-across (DAT-737, DAT-809,
DAT-740). Plus the grammar unlocks that belong with it: **extract predicates (DAT-838)** and
**grounding disambiguation (DAT-709)**, and the additivity verdicts (DAT-857/868).

**Exit:** the engine's own SQL computes one per-entity unit metric, drilled one level down
the ladder, and A3 has graded it.

### B2 (Phase 4, strand 3) — The facet and the coverage map

The `dimension` facet on concepts and metrics — sequenced on the ontology parse surface
with DAT-883 and DAT-724, which already carry a "do not run both" constraint. Then the
coverage map as a read over rows that already exist (grounding edges, readiness bands,
additivity verdicts, temporal coverage) grouped by facet.

**The gate that keeps it honest:** *lit* requires at least one unit metric of that dimension
to ground **and** grade. Grounded-but-ungraded is *partial*. Everything else is dark.

**Exit:** the map renders and is correct on today's reality — and an oracle fails if any
dimension reads lit without a graded metric behind it.

### B3 (Phase 4, strand 2) — Priors into frame

Seed induction with the dimension priors instead of the nearest shipped vertical; extend the
metric family so a framed vertical acquires its dimensions' unit metrics, user-edited, not
just concepts. Add the provisional (structure-only) coverage read at the staging hub, and
the per-dimension starter recipes.

**Exit:** a novel dataset frames into a model whose concepts and metrics carry dimension
facets, with no finance vocabulary leaking in, and binding precision on a corpus with truth
does not degrade (RFC 5 gate).

### B4 (Phase 4, strand 1) — The target operator, then root-causing

Ship the comparison term with the estimators that need no new runtime — **prior period**,
**internal peer**, **definitional standard** — plus **entity birth/death** in the same
slice, as a step kind in the answer path with the disclosure riding the band annotation
that is already there. Then the root-causing direction: drivers + drill + validation
evidence composed into *why*, which is what a deviation is for.

**Exit:** a deviation is surfaced with its target named, the others' rejection reasons
stated, and a band that includes A3's pipeline term; an oracle grades selection and
abstention.

### B5 — Demand + Offer lit, then allocation

With A1's corpus and B1–B4 in place: DB1 per customer and per product group, disclosed,
drillable, graded — two dimensions lit. **Then** allocation as a first-class object (named,
plural, versioned, inspectable, one scheme spanning dimensions) which unlocks DB2,
cost-to-serve, shared-capacity costing and every what-if propagation.

### B6 — Capital completed, then what-if (forecast parked)

Inventory and AR arrive with A1; Capital finishes (CCC down the ladder, DSO by customer,
DPO by supplier) and delivers the first genuine cross-dimension query on the bus matrix.
Then what-if (DAT-752/753 with DAT-754), whose predecessors — trusted targets and explicit
allocation — are now in place. **Forecast is no longer in this step**: per the 2026-07-27
decision it is parked (DAT-750/751 + the backtest harness) until a customer asks for
projected targets, and it would then plug into the operator's existing empty slot without
resequencing anything.

### B7 — Supply, Capacity, Throughput

Each gated on: a borrowed documented schema, an A1 generator family, and — for Throughput —
the person-grain quarantine (typed marker, binding-time refusal, and an oracle proving the
refusal fires). A design partner with real procurement data accelerates Supply once its
shape has become a generator family. Partner rows never leave the partner's perimeter.

---

## What a prospect sees, and when

The point of the two-lane shape is that the story is demonstrable long before the last
gate closes.

| After | The demo |
| :---- | :---- |
| A2 + the staging hub read | "Here is what your database can and cannot tell you about your operating model" — from their own schema, in the first ten minutes, no ingestion |
| B2 | The coverage map on a real run: lit / partial / dark per dimension, with the dark branches named and priced |
| B3 | Onboarding a novel dataset that comes back with *their* model — concepts, metrics, cycles — organised by dimension |
| B4 | "This is down 4%, against a prior-period target, and that is inside the band — here is what would be outside it" |
| B5 | Contribution margin per customer and per product group, calculation disclosed, drillable |
| B5 + allocation | "Profitable under key A, not under key B" — side by side |
| B6 | Profitable on margin, unprofitable on cash; then levers (projected targets only if forecast is ever unparked) |

## Work items

| Item | Lane | Effort | Ticket |
| :---- | :---- | :---- | :---- |
| Operating-model generator (customer/order/product chain first) | A1 | large, and the highest-leverage item here | **DAT-884** (DAT-689 stays closed) |
| Levers as DGP parameters, per lever type | A1 | medium; the price-level precedent exists | with DAT-884 / DAT-744 |
| Dimension prior library (vertical-neutral; Demand/Offer/Capital first) | A2 | medium | **DAT-885** |
| Grade the product answer path → pipeline-error term | A3 | medium | DAT-687 (**green-lit 2026-07-27**) |
| Verdict values, wild rows, dimension coordinate, reducer variance | A4 | small | extends DAT-862 (scoped there 2026-07-27) |
| Extract predicates (declaration side) | B1 | small | DAT-838 |
| Grounding disambiguation | B1 | medium | DAT-709 |
| Axis catalog + per-axis additivity | B1 | medium | DAT-879, DAT-857, DAT-868 |
| `dimension` facet on the ontology | B2 | small | new; sequence with DAT-883/DAT-724 |
| Coverage map (post-run) + honesty gate | B2 | small | new |
| Provisional coverage read + starter recipes | B3 | small | new (RFC 6) |
| Priors as the frame induction seed; metric family per dimension | B3 | medium | DAT-855 strand 2 |
| Target operator (prior period, peer, standard, birth/death) | B4 | medium | DAT-855 strand 1 |
| Allocation object (named, versioned, plural) | B5 | large | new |
| Backtesting harness | B6 | medium | parked with DAT-750/751 (2026-07-27) |
| Person-grain quarantine (marker + refusal + oracle) | B7 | medium | new |
| Licence-and-content audit, recorded per dataset | cross | small, mandatory | new |

**On a "binding regression suite".** The drafts propose MMTU. We already own the
capability: the execution cube, `metadata_truth.yaml`, and 27 graded oracle modules
including concept-binding precision and recall. Extend it with the per-facet binding gate.
A second harness is a second thing to maintain, not a second signal.

## What not to do

- **Do not stay in finance because the generator is a ledger.** That is the tail wagging the
  dog. The product is performance analytics; the generator generates performance-analytics
  data. What survives from the old rule is narrower and still right: **borrow schema shapes
  from documented real systems** rather than inventing them, and **keep the wild tier** as
  the counterweight to designer bias. Bias is managed, not avoided by abstinence.
- **Do not let an unverified public dataset reorder the roadmap.** It changes the demo, not
  the proof.
- **Do not ship forecast before the operator**, or what-if before allocation.
- **Do not let a dimension read *lit* on a metric that grounds but is not graded.** The
  coverage map lying costs more than the dark cell it was covering.
- **Do not gate the build on the measurement.** A3 gates the *claim* "this deviation is
  significant". It does not gate building the operator, the priors or the corpus.
- **Do not build a second eval framework.** Freeze the assertion grammar; extend the cube.

## Open questions

**Concept model**
- Archetype detection: inferred from the recovered model, declared at onboarding, or both
  with disagreement as signal? It is also the facet-gating signal (RFC 0), which raises its
  value above "ordering device".
- Facet induction: does the LLM assign the dimension facet during frame, or is it derived
  from which prior template a concept matched? Derivation is cheaper and auditable;
  induction generalises better. Probably derive first, revisit with DAT-738.
- Metric template versioning: when a canonical template changes, how do existing reports
  migrate? Reports already flag data drift; template drift needs an analogous flag.
- Customer-facing naming: "performance dimensions" internally; the cockpit should probably
  show plain groups — "Your customers", "What you sell", "Your suppliers", "What you run
  on", "How work flows", "Where your cash sits".
- ~~`reporting_intent` is still a live readiness intent while the pivot retired reporting as a
  target.~~ **RESOLVED 2026-07-29 (engine PR #539):** renamed to `presentation_intent`,
  weights untouched — the key name only, so no band value moves. Eval's
  `intent_readiness.yaml` follows in the same commit (12 occurrences).

**The run model and the dimensions** (grounded 2026-07-27; a design paragraph for the
DAT-855 strand-3 /refine, not a build item)

- The artifact split is precise and coherent: 28 tables carry `run_id` and participate in
  HEAD (the measurement layer — profiles, relationships, enriched views, hierarchies, bus
  matrix, entropy, validation `sql_used`), 15 do not (the model layer — concepts, metrics,
  validations, cycles, conventions, the teach `config_overlay`, grounded `sql_snippets` —
  versioned by `superseded_at`, scoped by vertical). Validation *verdicts* are never stored
  (ADR-0017: computed on demand).
- **Ruling for now: no run-per-dimension.** The atomic promote ("every run measures the
  whole catalog") is load-bearing; the facet as a coordinate on catalog-grain artifacts
  gives per-dimension reads, grading and the coverage map without per-dimension runs. The
  real need hiding behind the idea — run economy when a customer lights a new dimension
  later — belongs to the cache lane (DAT-861), not run-model surgery.
- Nothing is foreclosed: the head target is a free string explicitly designed for new
  shapes (`snapshot_head.py`), so a per-dimension target can be added later if incremental
  adoption demands it.

**Targets and simulation** — see RFC 1 (pipeline-error unit, plan grain binding, plan
freshness, backtest display, interval presentation, scenario composition, ownership).

**Commercial**
- Does the coverage map's dark/partial structure become the concierge report catalog
  verbatim, or a curated subset?
- Which dimension does the website lead with? Demand + Offer for credibility, Supply for the
  flagship question. Those are not the same dimension — a positioning decision, not a
  product one.
