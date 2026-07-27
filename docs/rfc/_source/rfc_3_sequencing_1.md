# RFC 3 — Sequencing, decisions and open questions

*Status: draft · Part 3 of 4 · Highest churn rate of the four; kept separate so RFC 0 stops moving*

---

## Decisions already taken

Recorded so they stop being re-litigated.

| Decision | Resolution |
| :---- | :---- |
| Dimension count | Six: Demand, Offer, Supply, Capacity, Throughput, Capital. Customers split into Demand and Offer; Assets generalized to Capacity; Capital added as a peer of the finance ontology, not a branch of it |
| Industry handling | Archetypes weight the dimensions; they never filter them. Vertical vocabulary parameterizes within a dimension |
| Allocation schemes | Named, plural, comparable side by side. Not one hidden scheme |
| Prior strength | Priors propose, never suppress. Promoted from open question to hard rule in RFC 0 |
| Target operator | Evidence-ranked, not availability-ranked. Forecast is a first-class estimator; every target carries a model, an interval and an evidence grade |
| What-if | The inverse of the existing grammar, not a separate subsystem. Typed levers only |

## Sequencing

**Revised.** The earlier stage order was justified by data scarcity in Supply, Capacity and Throughput. That justification did not survive the source review in RFC 2: Supply has an openly licensed 1.6M-event purchase-to-pay corpus, and Capacity has a public-domain fleet dataset in which every metric is a literal column. The constraint that actually shapes the order is now **licence and cross-dimension coherence**, not availability — plus engineering effort, which is once again allowed to matter.

### Stage 1 — Grammar before dimensions

**Forecast targets and deviation significance.** Applies to the finance ontology that already ships. Lights every *partial* branch without requiring a single new data source, and delivers the one line no competitor says: *this deviation is larger than the target's own uncertainty, and here is the target's track record*. Highest ratio of user-visible value to integration work anywhere in the roadmap, and it is dimension-independent.

Ship this first. It makes every subsequent dimension better on arrival.

### Stage 2 — Demand and Offer together

They share the granularity ladder, the DB ladder and the price–volume–mix bridge, and separating them means building the ladder twice. Both are demoable on real, openly licensed data today — AdventureWorks OLTP under MIT, which is the one corpus that spans all six dimensions for a single fictional firm and is therefore the demo spine (RFC 4). Note the change: **rel-salt is out of the demo path**, CC-BY-NC-SA blocks commercial use. It remains usable for internal binding evaluation.

Flagship: the contribution-margin ladder per customer and per product group, with the allocation rule disclosed and two named schemes comparable side by side.

### Stage 3 — Supply

**Moved up from stage 4.** The strongest flagship question in the model (*which supplier is really costing us money — price plus delays plus claims?*), natively multi-source, and no longer data-blocked. AdventureWorks `PurchaseOrderDetail` carries real `RejectedQty` (3.12% of units — the quality signal we thought had to be invented) alongside `ProductVendor.AverageLeadTime` and `StandardPrice`. BPI Challenge 2019 (CC BY 4.0) supplies the full purchase-to-pay event corpus with vendor, goods receipt, invoice, EUR value and four explicit matching flows. SCMS/USAID joined to openFDA enforcement gives an external claim-to-spend ratio on real named vendors.

The prerequisite work item changed accordingly: not "build a synthetic claim layer" but **relationalize BPI 2019's XES into PO / item / receipt / invoice tables**, which is mechanical.

A design partner with real procurement data including quality notifications is still the single highest-value contribution and remains a selection criterion — but it is now an accelerant, not a gate.

### Stage 4 — Capacity

**Moved up from stage 5.** Cincinnati Fleet Services is public domain, refreshed daily, spans 2008 to present, and holds `labor_cost`, `parts_cost`, `total_cost`, `downtime_hrs_shop`, `downtime_hrs_user`, `delay_hours`, `labor_hours` across 332,420 work orders plus `fuel_cost`, `deprec_cost`, `pm_labor_hrs` and `fixed_monthly_cost` across 818,903 asset-months, joined on one key with a parent hierarchy. Cost per capacity hour, utilization and total cost of ownership are all direct computations. Hill of Towie (CC-BY-4.0) adds a second archetype; US BTS aviation adds the allocation showcase (Form 41 cost by carrier × aircraft type allocated down to tail-numbered flights).

The remaining work is vocabulary, not data: fleet labels have to map onto line, machine and site for other archetypes.

### Stage 5 — Capital, then Throughput

**Capital** is cheap — mostly attribution rather than allocation, computable from stock and order data already connected in stage 2, and it pairs with Demand for the customer ranking nobody has (profitable on margin, unprofitable on cash). It sits here rather than earlier only because AdventureWorks has no AP subledger, so days-payable and a true working-capital statement need either Wide World Importers or partner data.

**Throughput last**, and now for a sharper reason than "no data". The shape is fully available — 72,591 work orders, 67,131 routing operations, 58.4% schedule variance, real scrap reasons — but `ActualCost` equals `PlannedCost` on every routing row in AdventureWorks, and the one public log with true shop-floor vocabulary (4TU Production Analysis) has 225 cases, no money and no open licence. Throughput is therefore the only dimension whose demo requires disclosed synthesis. It also carries the compliance design (aggregate entities only), which is cheaper to get right once with a real works-council conversation behind it.

### Cross-cutting, prioritized by how often *partial* occurs in real pilots

- **Plan ingestion from spreadsheets.** Lights the plan branch everywhere. Legitimate first-class use of file import.
- **Projection** (forward what-if) on dimensions already lit and already allocated.
- **Goal-seek**, after projection is trusted. Inverting a model users do not yet believe is premature.
- **Scenario comparison surface** — side-by-side scenarios, side-by-side allocation schemes.

Ship one dimension at a time and let the coverage map carry the roadmap story honestly. "This dimension is coming" is a badge, not a promise.

## Data work items

Revised against the source review. Three items are obsolete, three are new.

| Item | Blocks | Effort |
| :---- | :---- | :---- |
| ~~Synthetic claim / QA layer over AdventureWorks~~ | — | **obsolete** — `RejectedQty` is real |
| ~~Capacity synthetic generator~~ | — | **obsolete** — Cincinnati is public domain |
| Licence audit of every demo source, recorded per dataset | all demo work | small, mandatory, do it once — rel-salt and Olist are already casualties |
| Relationalize BPI 2019 XES → PO / item / receipt / invoice tables | Stage 3 Supply | mechanical, medium |
| Cost-variance synthesis over AdventureWorks routing, with disclosure banner | Stage 5 Throughput | small; the disclosure is the hard part |
| Cincinnati fleet → generic capacity vocabulary mapping | Stage 4 Capacity | small |
| Carrying-cost and service-level parameter defaults | Capital simulation levers | small, but must be named and versioned |
| Backtesting harness for forecast targets | Stage 1 credibility | medium; also the evidence for the backtesting display |
| Binding regression suite | prior-strength rule enforcement | see note below |

**On the binding regression suite.** MMTU (NeurIPS 2025) is not demo data and is not a source of business examples — it is a benchmark of table *operations*: joins, matching, transformation, cleaning, roughly 25 task families. That makes it the right harness for regression-testing the three-witness binding layer as prior surface grows from one ontology to six. Different shelf from RelBench and CTU; both shelves are useful.

## Open questions

**Concept model**

- Vertical vocabulary packs: separate artifact per vertical, or learned entirely from framing? Where does a "manufacturing labels" pack live?
- Archetype detection: inferred from the recovered model, declared by the user at onboarding, or both with disagreement as signal? Inference is more in keeping with the platform's register, declaration is more reliable.
- Coverage map placement: workspace home vs. Model surface vs. both.
- Metric template versioning: when a canonical template changes, how do existing reports migrate? Reports already flag data drift; template drift needs an analogous flag.
- Customer-facing naming: "performance dimensions" internally; the cockpit should probably show plain groups — "Your customers", "What you sell", "Your suppliers", "What you run on", "How work flows", "Where your cash sits".

**Forecast and simulation** — see RFC 1's open questions (forecast gate, backtesting display, interval presentation, scenario composition, ownership, plan freshness typing).

**Commercial**

- Does the coverage map's dark/partial branch structure become the concierge report catalog verbatim, or a curated subset?
- Which dimension does the website lead with? Current answer implied by sequencing: Demand + Offer for credibility, Supply for the flagship question. Those are not the same dimension, which is a positioning decision, not a product one.
