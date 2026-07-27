# RFC 0 — Performance Dimensions: the concept model

*Status: draft for discussion · Author: Flo (with Claude) · Scope: product architecture*
*Part 0 of 4 — see RFC 1 (Forecast & simulation), RFC 2 (Dimension specifications), RFC 3 (Sequencing & open questions)*

---

## Summary

Data Raum ships one predefined domain ontology (finance) and frames every other domain in plain language per workspace. This RFC generalizes that pattern into a small set of **performance dimensions** — Demand, Offer, Supply, Capacity, Throughput, Capital — shipped as ontology priors over the recovered operating model, unified by a **unit-economics grammar**, evaluated through a universal **target operator**, and surfaced through a **coverage map** that tells the user which dimensions their data can carry.

Three axes, kept strictly orthogonal:

- **Dimension** — what part of the conversion is being measured. Universal, six of them.
- **Archetype** — which dimension carries the binding constraint for this kind of business. Five of them, a prior over weighting and entry point, never over the dimension list.
- **Vertical vocabulary** — labels and measures within a dimension. Parameterization only; it never multiplies dimensions.

The dimensions are priors, never templates. The company's own recovered model remains ground truth. Where a company does not fit a dimension, it stays dark rather than being force-filled.

## Motivation

1. **Executives compare in unit economics.** What a CXO actually asks reduces to *€ per unit, per entity, versus an expectation*: cost per customer, margin per product group, cost per machine hour, claim cost per supplier, scrap cost per shift. A product that computes arbitrary KPIs answers questions; a product that computes *comparable* unit economics answers the CXO's job. Comparability, not coverage, is the requirement.

2. **Every performance question is a deviation question.** "How is X performing?" always means "compared to what?" Plan-vs-actual is therefore not one dimension among several; it is the **operator applied to all of them**. (Detailed in RFC 1.)

3. **The pattern already exists in the product.** The finance ontology in the box *is* a predefined domain ontology bound to discovered data with measured confidence. This does not introduce a new mechanism; it generalizes a proven one.

## The six dimensions

A firm captures demand, sells an offer, buys supply, holds capacity, performs work, and ties up cash doing all of it. Those are the six.

| Dimension | Plain name | Canonical entities | Example unit metrics | ROIC term |
| :---- | :---- | :---- | :---- | :---- |
| **Demand** | Your customers | customer, segment, channel, order, quote | revenue per customer, cost-to-serve per channel, concentration, retention | margin |
| **Offer** | What you sell | product, product group, service, contract, SKU | contribution margin per level (DB1/2/3), mix effect, price realization | margin |
| **Supply** | Your suppliers | supplier, carrier, subcontractor, PO, goods receipt, invoice, claim | effective cost per unit delivered (price + delay + claims), OTIF, claim-to-spend | margin |
| **Capacity** | What you run on | machine, line, vehicle, site, headcount, seat, licence · downtime event, maintenance order | cost per capacity hour, utilization, output per unit of capacity | both |
| **Throughput** | How work flows | shift, line, team, process step, work order, project *(never individual — see Compliance)* | cost per process step, yield, cycle-time efficiency, rework rate | margin |
| **Capital** | Where your cash sits | inventory position, receivable, payable, capex item, work in progress | days inventory / receivable / payable, cash conversion cycle, capital per unit of output | turnover |

The ROIC column is not decoration. It is the argument for why these six and not others: return on capital decomposes into margin × capital turnover, and every dimension here is an operating driver of one term or the other. Anything that drives neither does not belong in an operating model.

**Capital is a peer dimension, not a branch of finance.** The finance ontology is ledger truth — what was booked. Capital is an operating question — what the operating decisions tied up and for how long. Half of return on capital lives in the turnover term, and it is moved by inventory policy, terms, and capex timing, not by accounting.

**Offer is a peer dimension, not a branch of Demand.** The standard price–volume–mix bridge treats mix as its own term. Mix is an offer-side decision; a customer-side dimension cannot hold it, and mix is routinely the largest unexplained line in a margin walk.

### Lineage

Not one framework; a composition of recognizable ones. DuPont/ROIC for the spine. Cash conversion cycle (Richards & Laughlin, 1980) for Capital. SCOR (ASCM) for Source / Make / Deliver, whose own metric attributes already include cash-to-cash cycle time. Porter's value chain for the primary-activity cut, whose known gap is exactly the capital term. APQC's Process Classification Framework as precedent for the architecture itself: one cross-industry spine plus published industry variants. Theory of Constraints for the archetype idea. Hayes & Wheelwright (product-process matrix) and Schmenner (service process matrix) for the archetype classification.

Deliberately *not* the Balanced Scorecard: BSC is a strategic instrument with a Learning & Growth quadrant that has no representation in any system of record. This is an operating model and excludes anything not computable from operational data.

## Archetypes: which dimension binds

The dimension list is universal. What differs by industry is **which dimension carries the constraint** — and therefore where onboarding starts, which dark branch is expensive, and which metric earns the first screen.

| Archetype | Examples | Binding dimension | Entry metric |
| :---- | :---- | :---- | :---- |
| **Asset-intensive conversion** | discrete & process manufacturing, logistics, utilities, hospitality, healthcare providers | Capacity | cost per capacity hour, utilization vs. downtime |
| **People-intensive delivery** | consultancies, agencies, staffing, field service, care | Capacity (as hours) × Throughput | utilization, realization, bench |
| **Inventory-intensive distribution** | retail, wholesale, distribution, e-commerce | Capital × Supply | turns, stockout and markdown cost, days inventory |
| **Contract-intensive recurring** | SaaS, insurance, telco, maintenance contracts | Demand | retention by cohort, revenue bridge, cost-to-serve |
| **Project-intensive one-off** | construction, engineering, systems integration, shipbuilding | Throughput × Capital | cost-at-completion vs. plan, change-order exposure, WIP |

Hard rule: **the archetype weights, it never filters.** An asset-intensive company that also runs a service contract book gets Demand lit if the data supports it. The archetype changes the order things are offered in and the language of the first screen, nothing else.

## The unit-economics grammar

Every dimension speaks one grammar:

```
entity × metric-per-unit × comparison
```

A **unit metric** is a numerator/denominator pair over concepts in the metrics graph (cost ÷ customer, margin ÷ product group, € ÷ machine hour, days ÷ inventory turn), computed at **every granularity for which join keys exist**, and always evaluated against a **target**.

RFC 1 extends this grammar in two directions: forecast as a fourth target source, and simulation as the inverse operator (fix the metric, solve for the lever).

## The target operator (Soll)

"Compared to what?" resolves against four estimators, evidence-ranked rather than availability-ranked:

1. **Plan**, if current and at matching granularity. A stale or wrong-grain plan is a worse target than a naive one and is demoted, not preferred. Plan freshness is typed evidence.
2. **Forecast**, when history length and stability clear the gate.
3. **Prior period** — the persistence estimator.
4. **Internal peer** — the cross-sectional estimator, offered alongside rather than instead of the others, because it answers a different question: is this entity worse, or is the whole class worse?

Every target carries a stated model, an uncertainty interval, and an evidence grade — which is what makes a deviation *testable* rather than merely displayed. Full treatment in RFC 1.

Hard rule: **the system always states which target it used and why the others were not.** Silent fallback is the failure mode of every planning tool on the market.

## The granularity ladder

Customer → segment → product group → product → order: the same metric, rolled consistently across levels, drillable in either direction. This formalizes the trade-review moment ("category −8% — why?") as a descent on the ladder rather than an ad-hoc analysis, and it is the product-side embodiment of "aggregates hide problems; the breakdown surfaces them."

Each dimension has its own ladder; RFC 2 specifies them.

## Binding: priors, not templates

Each dimension ships as an **ontology prior** for the learnable surface: concept schemata, expected relations, and canonical unit-metric templates. Binding discovered tables and columns to these priors is an evidence question like any other — the three witnesses propose, disagreement is signal, entropy measures fit, corrections enter through teach and persist as typed evidence.

Three hard rules, all of them load-bearing:

- **The company model outranks the prior.** Dimensions are lenses over the recovered operating model, never a grid the data is pressed into. Predefined depth *plus* company-specific fit is precisely what neither a rigid tool nor a bare LLM offers. If priors ever silently override recovered structure, we become the standard-schema tool we out-position.
- **Priors propose, never suppress.** A prior may raise a candidate hypothesis. It may not lower the standing of a company structure that the evidence supports better. This is the single rule that protects the differentiator, and it becomes more important with six dimensions than it was with four, because prior surface grows with the dimension count.
- **Non-fit stays dark.** A services company without machines shows an unlit Capacity dimension in its machine sense, not a hallucinated one. Darkness is information.

## The coverage map

A workspace-level surface showing, per dimension: **lit** (data supports it, metrics computable), **partial** (actuals yes, plan no), **dark** (no supporting data found), plus two states from RFC 1 — **forecastable** (enough clean history to fit and validate a model) and **simulatable** (structural paths and allocation rules present to propagate a lever).

The archetype makes dark meaningful. Today dark reads as a flat gap. With an archetype prior it splits:

- **dark and off-archetype** — a badge, not a gap. "You are a contract business; you have no machines. Correct."
- **dark and load-bearing** — a named, priced next step. "You are inventory-intensive and Capital is dark. That is where your money is."

One artifact, three jobs: onboarding progress, honest confidence display in the platform's existing register, and a built-in expansion motor where each dark, partial, not-yet-forecastable or not-yet-simulatable branch is a named next step. The concierge report catalog, the website's breadth section, and this product surface become the same object in three views.

This is also what stops six dimensions from making first-run coverage look worse than four did.

## Allocation

"Cost per customer" is not an aggregation; it is an **allocation**. Direct costs are trivial; overheads (freight batch invoices, sales, manufacturing overhead) require keys — and different keys yield different truths. This is exactly where such analyses die in Excel: everyone allocates differently, nobody remembers how.

For Data Raum this is the provenance stage: **the allocation rule is an explicit, versioned part of the model, inspectable from every figure** — "cost per customer under key X; here is the rule; here are the rows." The German-native canonical form is the contribution-margin ladder (DB1/DB2/DB3): *Deckungsbeitrag per customer, at every level, with the calculation disclosed* is a sentence every industrial CFO understands immediately and nobody currently delivers cleanly.

**Decided: named schemes, plural, comparable side by side.** A single hidden scheme is the Excel failure mode we are indicting. "Profitable under key A, not under key B" is the demo, not an edge case. It is also a hard requirement of RFC 1: a scenario computed under an unnamed allocation scheme is not reproducible.

## Compliance by design (Throughput)

Individual performance monitoring is co-determination territory in Germany (§87 BetrVG; systems merely *capable* of monitoring suffice) plus GDPR. The dimension encodes granularity **in the schema**: canonical entities are shift, line, team, process step, work order. Bindings at person level are quarantined by default rather than surfaced. Compliance as a product property, not a sales guideline — and in the German market, mitbestimmungsfest by design is itself a selling argument.

Note that this constraint bites hardest exactly where the people-intensive archetype needs Throughput most. RFC 2 specifies the aggregate-entity workaround (role/grade/team, never person) that keeps consulting-style utilization computable without touching individual monitoring.
