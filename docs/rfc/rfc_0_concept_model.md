# RFC 0 — Performance dimensions: the concept model

*Status: golden (grounded against the code 2026-07-27) · Part 0 of 6*
*RFC 1 targets & simulation · RFC 2 dimension specs · RFC 3 sequencing · RFC 4 demo data · RFC 5 evaluation · RFC 6 product surfaces*
*Evidence for every grounding claim: [`rfc_verification.md`](rfc_verification.md)*

---

## Summary

DataRaum ships one predefined domain ontology (finance) and frames every other domain
in plain language per workspace. This RFC generalizes that pattern into a small set of
**performance dimensions** — Demand, Offer, Supply, Capacity, Throughput, Capital —
shipped as ontology priors over the recovered operating model, unified by a
**unit-economics grammar**, evaluated through a universal **target operator**, and
surfaced through a **coverage map** that tells the user which dimensions their data can
carry.

Three axes, kept strictly orthogonal:

- **Dimension** — what part of the conversion is being measured. Universal, six of them.
  A **facet on concepts and metrics**, not a vertical (see *Dimensions are facets*).
- **Archetype** — which dimension carries the binding constraint for this kind of
  business. Five of them; a prior over weighting and entry point, never over the
  dimension list.
- **Vertical vocabulary** — labels and measures within a dimension. One vertical per
  workspace; parameterization only; it never multiplies dimensions.

The dimensions are priors, never templates. The company's own recovered model remains
ground truth. Where a company does not fit a dimension, it stays dark rather than being
force-filled.

## Motivation

1. **Executives compare in unit economics.** What a CXO asks reduces to *€ per unit, per
   entity, versus an expectation*: cost per customer, margin per product group, cost per
   machine hour, claim cost per supplier, scrap cost per shift. A product that computes
   arbitrary KPIs answers questions; a product that computes *comparable* unit economics
   answers the CXO's job. Comparability, not coverage, is the requirement.

2. **Every performance question is a deviation question.** "How is X performing?" always
   means "compared to what?" Plan-vs-actual is therefore not one dimension among several;
   it is the **operator applied to all of them** (RFC 1).

3. **The pattern exists in the product — one half of it is proven.** The finance ontology
   is a predefined domain ontology bound to discovered data with measured confidence. The
   **concept→column** half is proven (the eval grades concept bindings and semantic roles
   on the finance corpus and they hold). The **concept→SQL** half is not: DAT-709 has two
   distinct balance-sheet concepts grounding to the identical extract, which makes
   `current_ratio ≡ 1.0`. Six dimensions multiply the prior surface by six, so the
   grounding-disambiguation defect must be closed before the surface grows, not after.

## The six dimensions

A firm captures demand, sells an offer, buys supply, holds capacity, performs work, and
ties up cash doing all of it. Those are the six.

| Dimension | Plain name | Canonical entities | Example unit metrics | ROIC term |
| :---- | :---- | :---- | :---- | :---- |
| **Demand** | Your customers | customer, segment, channel, order, quote | revenue per customer, cost-to-serve per channel, concentration, retention | margin |
| **Offer** | What you sell | product, product group, service, contract, SKU | contribution margin per level (DB1/2/3), mix effect, price realization | margin |
| **Supply** | Your suppliers | supplier, carrier, subcontractor, PO, goods receipt, invoice, claim | effective cost per unit delivered (price + delay + claims), OTIF, claim-to-spend | margin |
| **Capacity** | What you run on | machine, line, vehicle, site, headcount, seat, licence · downtime event, maintenance order | cost per capacity hour, utilization, output per unit of capacity | both |
| **Throughput** | How work flows | shift, line, team, process step, work order, project *(never individual)* | cost per process step, yield, cycle-time efficiency, rework rate | margin |
| **Capital** | Where your cash sits | inventory position, receivable, payable, capex item, work in progress | days inventory / receivable / payable, cash conversion cycle, capital per unit of output | turnover |

The ROIC column is the argument for why these six: return on capital decomposes into
margin × capital turnover, and every dimension is an operating driver of one term or the
other. Anything driving neither does not belong in an operating model.

**Capital is a peer dimension, not a branch of finance.** The finance ontology is ledger
truth — what was booked. Capital is an operating question — what the operating decisions
tied up and for how long.

**Offer is a peer dimension, not a branch of Demand.** The price–volume–mix bridge treats
mix as its own term; mix is an offer-side decision and is routinely the largest
unexplained line in a margin walk.

### Lineage

DuPont/ROIC for the spine. Cash conversion cycle (Richards & Laughlin, 1980) for Capital.
SCOR (ASCM) for Source / Make / Deliver. Porter's value chain for the primary-activity
cut, whose known gap is exactly the capital term. APQC's Process Classification Framework
as precedent for the architecture itself: one cross-industry spine plus published industry
variants. Theory of Constraints for the archetype idea. Hayes & Wheelwright and Schmenner
for the archetype classification.

Deliberately *not* the Balanced Scorecard: its Learning & Growth quadrant has no
representation in any system of record. This is an operating model and excludes anything
not computable from operational data.

## Dimensions are facets, and narrowness is preserved by scoping

The pipeline works because a **narrow** vocabulary is mapped onto selected data. That is
not an accident of the finance ontology; it is the mechanism. An empty vocabulary fails
loud rather than grounding against nothing (`_adhoc` refuses), and grounding precision is
a function of how few plausible concepts a column has to choose between. Six dimensions
must not dilute that. This section says exactly how they don't.

### Why not one vertical per dimension

- A **vertical** resolves to `shipped` / `framed` / `placeholder` / `unknown`
  (`core/vertical.py`) and is a model pack: concepts, conventions, and the executable
  knowledge over them — validations, cycles, metrics. `finance` is shipped; a customer
  domain is *framed* in the cockpit and written to the workspace.
- **A workspace carries exactly one.** `worker/workflows.py::_single_vertical` raises on
  more than one — *"multi-vertical grounding not yet supported … until ontology merge
  lands."*
- So six verticals means six workspaces per company, and the cross-dimension compound
  queries that justify the whole model (Supply × Capital, Demand × Capital) become
  structurally inexpressible: separate schemas, separate property graphs, separate enriched
  views. It also splits the evaluation axis six ways.

### The facet does not grow the workspace's vocabulary — it classifies it

This is the point that makes narrowness a non-issue, and it is easy to miss.

A workspace's vocabulary is **the customer's own framed model** — the ~20–40 concepts
induced from their schema and edited by them at frame time. The dimension facet is a *tag*
on those concepts, not an addition to them. A manufacturer's framed model does not get
larger because we know that `work_order` is Throughput and `receivable` is Capital.

The prior library — six dimensions' worth of canonical entities and unit-metric templates
— lives at **frame time**, where it is a *proposal source*, not a runtime vocabulary. The
induce/declare round-trip prunes it: the LLM proposes over the actual schema, the user
edits, and only what was declared is written. "Priors propose, never suppress" is what
keeps the workspace narrow; seeding all six dimensions' full template sets into every
workspace is the failure mode that rule exists to prevent.

### Narrow at inference: the facet is a gate, not a superset

Where the prior *could* still widen the candidate set is per-column grounding. Three
scopings keep it narrow, in increasing strength:

1. **Data scoping.** A facet is only a candidate at all if the recovered model has entities
   for it. No asset table, no Capacity candidates — the same test that makes the coverage
   map say *dark*.
2. **Archetype weighting.** The archetype prior (declared at onboarding or inferred) orders
   which facets are attempted first and which are unlikely. It weights; it never filters —
   a contract business that turns out to have machines still gets them.
3. **Table-local scoping.** Grounding already happens per column within a table whose role
   and grain are known. A facet inherits from the table's recovered entities, so a column
   on a work-order fact is not offered Demand's customer vocabulary.

Net effect: the concept set a single grounding call sees stays at today's size or smaller.
If it does not, that is measurable — see the gate below.

### Inference *between* facets: three carriers, and one prohibition

Cross-facet inference is the interesting half, and it must run on typed structure, never
on name similarity. Three carriers exist today:

1. **Concept edges** — `part_of`, `disjoint_with`, `reconciles_with` are already typed
   concept→concept relations. Cross-facet composition is exactly this: a receivable
   (Capital) `part_of` current assets; a Demand revenue measure `reconciles_with` a Capital
   receivable movement. These are declared in the ontology or witnessed by the
   reconciliation machinery, and their transitive closure is already walked.
2. **The recovered physical topology** — `og_references` / `og_has_dimension` / the
   enriched views. Whether a Demand entity can reach a Capital fact at all is a join
   question the engine already answers with evidence.
3. **Conformed dimensions** — the bus matrix (`og_conformed_dimension`). Two facts are
   comparable on a shared dimension only when that dimension is confirmed conformed across
   both. This is what makes "profitable on margin, unprofitable on cash" a legal single
   query rather than a plausible-looking wrong join.

**The prohibition: no cross-facet inference by name.** "Customer" appearing in a Demand
concept and in a Capital fact is not evidence that they are the same entity. The live
instance of exactly this failure is the relationship judge over-confirming
period/value-overlap pairs as FKs (DAT-723). A cross-facet claim needs an edge, a
verified join, or a conformance verdict — nothing else.

### The eval gate that makes this a property, not a hope

The risk this section manages is real and it is measurable: **binding precision must not
degrade as facets are added.** The eval already grades concept bindings against generated
truth. The gate: adding a dimension's priors must not reduce binding precision or recall
on a corpus with truth, measured per facet, before that dimension ships (RFC 5).

### Consequences

- A **fact table spans dimensions** — a ledger line carries Capital and Demand readings at
  once. *Lit / dark is computed per metric, never per table.*
- The facet lands on the ontology parse surface that DAT-883 and DAT-724 also touch; those
  are already sequenced against each other and this is the third rider (RFC 3).
- This is the content of an already-planned direction: DAT-855 strand 3 — *"defining a
  vertical as an ontology graph"* — and the dimension facet is what that graph classifies.
  The priors' delivery vehicle is frame induction (RFC 6), where they also replace a seed
  that is known to leak one industry's vocabulary into another's.

## The unit-economics grammar

Every dimension speaks one grammar:

```
entity × metric-per-unit × comparison
```

A **unit metric** is a numerator/denominator pair over concepts in the metrics graph
(cost ÷ customer, margin ÷ product group, € ÷ machine hour, days ÷ inventory turn),
computed at **every granularity for which join keys exist**, and always evaluated against
a **target**.

**Where the engine stands on each term** — this is the honest state, and it sets the
Stage-0 work in RFC 3:

| Term | Status | Gap |
| :---- | :---- | :---- |
| **entity** | *partly there* | The granularity ladder exists as `og_rolls_up_to` / `og_period_rolls_up_to` + the dimension-hierarchies phase, and drill-down over it is DAT-671 (in flight, blocked on the axis catalog DAT-879) |
| **metric-per-unit** | *not expressible* | Metric steps are `extract / constant / formula`; **extracts carry no predicate (DAT-838)**, so "revenue for segment B" cannot be declared. Metric grain is `scalar / series / table` with no per-entity declaration. Per-axis additivity verdicts — whether a roll-up on the ladder is even legal — are DAT-857/868 |
| **comparison** | *absent* | No target of any kind exists in the engine (RFC 1) |

RFC 1 extends the grammar in two directions: forecast as a fourth target source, and
simulation as the inverse operator.

## The target operator (Soll)

"Compared to what?" resolves against four estimators, evidence-ranked rather than
availability-ranked:

1. **Plan**, if current and at matching granularity. A stale or wrong-grain plan is a
   worse target than a naive one and is demoted, not preferred.
2. **Forecast**, when history length and stability clear the gate.
3. **Prior period** — the persistence estimator.
4. **Internal peer** — the cross-sectional estimator, offered alongside rather than
   instead of the others, because it answers a different question: is this entity worse,
   or is the whole class worse?

Every target carries a stated model, an uncertainty interval, and an evidence grade —
which is what makes a deviation *testable* rather than merely displayed.

Hard rule: **the system always states which target it used and why the others were not.**
Silent fallback is the failure mode of every planning tool on the market.

The interval must cover **two** error terms, not one: the model's own uncertainty *and*
the error the recovery pipeline introduces. That second term is unmeasured today; see
RFC 1 and RFC 5.

## The granularity ladder

Customer → segment → product group → product → order: the same metric, rolled
consistently across levels, drillable in either direction. This formalizes the
trade-review moment ("category −8% — why?") as a descent on the ladder rather than an
ad-hoc analysis.

This is not new work. It is DAT-671, in flight, on the shared result grid, with the axis
catalog (DAT-879) as its unlock and per-axis additivity (DAT-857/868) as its correctness
gate. Each dimension has its own ladder; RFC 2 specifies them.

## Binding: priors, not templates

Each dimension ships as an **ontology prior** for the learnable surface: concept
schemata, expected relations, and canonical unit-metric templates. Binding discovered
tables and columns to these priors is an evidence question like any other — the witnesses
propose, disagreement is signal, entropy measures fit, corrections enter through teach and
persist as typed evidence.

Three hard rules, all load-bearing:

- **The company model outranks the prior.** Dimensions are lenses over the recovered
  operating model, never a grid the data is pressed into.
- **Priors propose, never suppress.** A prior may raise a candidate hypothesis. It may not
  lower the standing of a company structure the evidence supports better. This is the rule
  that protects the differentiator, and it matters more with six dimensions than with one,
  because prior surface grows with the dimension count.
- **Non-fit stays dark.** A services company without machines shows an unlit Capacity
  dimension, not a hallucinated one. Darkness is information.

**These are design rules with no enforcement today.** Nothing tests that a prior cannot
outrank recovered structure. RFC 5 makes it an oracle: a prior-suppression check on a
corpus where the recovered structure and the prior deliberately disagree. Until that
oracle exists, "priors propose, never suppress" is an intention, not a property.

## The coverage map

A workspace-level surface showing, per dimension: **lit** (data supports it, metrics
computable), **partial** (actuals yes, plan no), **dark** (no supporting data found), plus
two states from RFC 1 — **forecastable** and **simulatable**.

This is the cheapest high-value item in the whole RFC set: it is a **read over rows that
already exist** — grounding edges (`og_grounding` / `og_grounded_by`), readiness bands
(`ready / investigate / blocked`, `entropy/loss.yaml`), additivity verdicts
(`og_additivity`), temporal coverage (`og_temporal_coverage`) — grouped by the new
dimension facet. No new measurement.

**Hard gate, or the map becomes the lie it is meant to prevent:** a dimension may read
*lit* only when at least one of its unit metrics **grounds and grades** — the engine's own
SQL computes it and an oracle confirms the value against known truth. Grounded-but-ungraded
is *partial*. Anything else is dark. Applying this gate to the shipped finance metrics
today already produces an honest, non-trivial map, because DIO has no inventory to ground
against and the AR half of DSO does not exist in our corpus.

The archetype makes dark meaningful:

- **dark and off-archetype** — a badge, not a gap. "You are a contract business; you have
  no machines. Correct."
- **dark and load-bearing** — a named, priced next step. "You are inventory-intensive and
  Capital is dark. That is where your money is."

One artifact, three jobs: onboarding progress, honest confidence display in the platform's
existing register, and a built-in expansion motor. It is also what stops six dimensions
from making first-run coverage look worse than one did.

## Allocation

"Cost per customer" is not an aggregation; it is an **allocation**. Direct costs are
trivial; overheads require keys — and different keys yield different truths. This is
exactly where such analyses die in Excel: everyone allocates differently, nobody remembers
how.

For DataRaum this is the provenance stage: **the allocation rule is an explicit, versioned
part of the model, inspectable from every figure**. The German-native canonical form is the
contribution-margin ladder (DB1/DB2/DB3): *Deckungsbeitrag per customer, at every level,
with the calculation disclosed.*

**Decided: named schemes, plural, comparable side by side.** "Profitable under key A, not
under key B" is the demo, not an edge case. It is also a hard requirement of RFC 1 — a
scenario computed under an unnamed allocation scheme is not reproducible.

**Nothing of this exists in the engine.** There is no allocation concept, rule, or
versioned artifact anywhere in the code. It is a new first-class object, not a
configuration of an existing one, and it is a dependency of what-if (RFC 1) as well as of
cost-to-serve (RFC 2). Sequencing consequence: **ship DB1 — direct costs, no allocation —
as the first disclosed ladder step.** A correct, disclosed DB1 is a real product moment;
an undisclosed DB2 is the failure being indicted.

## Compliance by design (Throughput)

Individual performance monitoring is co-determination territory in Germany (§87 BetrVG;
systems merely *capable* of monitoring suffice) plus GDPR. The dimension encodes
granularity **in the schema**: canonical entities are shift, line, team, process step,
work order. Bindings at person level are quarantined by default rather than surfaced.

**This is a missing capability, not a schema convention.** The engine binds *discovered*
columns; there is no person/PII typing and no quarantine path for a person-grained
binding. Real partner data will contain `worker_id`, and today it would be bound like any
other dimension. Making Throughput mitbestimmungsfest therefore requires: a typed
person-grain marker in the ontology, a binding-time refusal, and an eval oracle proving
the refusal fires on a corpus that contains a person column. That is a build item with a
gate, and it is why Throughput sequences late (RFC 3) — not because the data is thin.

Note that this constraint bites hardest exactly where the people-intensive archetype needs
Throughput most. RFC 2 specifies the aggregate-entity design (role / grade / team, never
person) that keeps consulting-style utilization computable.
