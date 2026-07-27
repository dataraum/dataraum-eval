# RFC 2 — Dimension specifications

*Status: draft · Part 2 of 4 · Reference material, grows per dimension as it ships*
*Depends on RFC 0 (concept model). Simulation levers referenced here are specified in RFC 1.*

---

## How to read this

One section per dimension. Each carries: canonical entities, the granularity ladder, canonical unit metrics, target notes (what the Soll looks like here), allocation notes, simulation levers, compliance notes where they apply, and **data availability** — what public data exists to build and demo this dimension, which is the practical constraint on sequencing.

Canonical metrics are **templates, not requirements**. A metric appears only where the recovered model supports it.

---

## Demand — "Your customers"

**Canonical entities.** Customer, account, segment, channel, region, quote, order, order line, contract.

**Ladder.** Customer → segment → channel → region, with order and order line as the leaf grain.

**Canonical unit metrics.**

| Metric | Definition | Notes |
| :---- | :---- | :---- |
| Revenue per customer / segment | revenue ÷ active entity | trivial, but the ladder entry point |
| Cost-to-serve | allocated operating cost (from Supply, Capacity, Throughput) ÷ customer or channel | the cross-dimension metric; requires an allocation scheme |
| Customer concentration risk | share of revenue in top 5% of customers | one of the few metrics executives already track and never automate |
| Order-to-cash duration | order placement → settlement | shared with Capital; same fact, two readings |
| Retention / cohort survival | active entities surviving period n | contract archetype only; dark elsewhere |

**Target notes.** Peer comparison is unusually strong here — segments are natural siblings and comparable by construction. Plan data is common at aggregate level and almost never at customer level, so this dimension is a frequent *partial*.

**Allocation notes.** Cost-to-serve is the flagship allocation and the hardest one. It is where named schemes earn their keep: freight by weight vs. by revenue vs. by order count produces three defensible and different customer rankings.

**Simulation levers.** Volume, price, mix (channel shift), allocation key.

**Data availability.** Strong. rel-salt (RelBench) is real SAP sales and ledger data. AdventureWorks and Northwind (CTU) both carry full customer/order/line structures. This dimension can be built and demoed on real relational data today.

---

## Offer — "What you sell"

**Canonical entities.** Product, product group, category, service, SKU, contract type, bundle, price list.

**Ladder.** Category → product group → product → variant/SKU.

**Canonical unit metrics.**

| Metric | Definition | Notes |
| :---- | :---- | :---- |
| Contribution margin ladder (DB1/DB2/DB3) | revenue − variable cost, then step-fixed layers | the canonical template; disclosed calculation is the point |
| Price realization | invoiced price ÷ list price | catches discount leakage; almost never visible in ERP reporting |
| Mix effect | the mix term of the price–volume–mix bridge | the reason Offer is its own dimension |
| Margin per unit of constrained resource | contribution ÷ the archetype's binding capacity unit | Theory-of-Constraints native; the single most under-computed metric in industry |
| Portfolio tail | share of SKUs below contribution threshold | pairs with concentration risk on the Demand side |

**Target notes.** Prior-period comparison at product level is noisy where the assortment churns; the model must handle entity birth and death without reporting phantom deviations. This is a real correctness requirement, not an edge case.

**Allocation notes.** DB2 and DB3 are allocation steps by definition. The ladder *is* the disclosure surface.

**Simulation levers.** Price, mix, volume, allocation key.

**Data availability.** Strong. Product hierarchies exist in AdventureWorks, Northwind, ClassicModels, rel-hm and rel-amazon. Cost structure sufficient for a real DB ladder is thinner — AdventureWorks has standard cost and list price, which is enough for DB1 and a defensible synthetic DB2.

---

## Supply — "Your suppliers"

**Canonical entities.** Supplier, vendor, carrier, subcontractor, purchase order, PO line, goods receipt, supplier invoice, claim, quality notification.

**Ladder.** Supplier group → supplier → PO → PO line, with carrier and site as cross-cuts.

**Canonical unit metrics.**

| Metric | Definition | Notes |
| :---- | :---- | :---- |
| Effective cost per unit delivered | price + delay cost + claim cost, per unit | the flagship. No ERP computes it; every procurement head wants it |
| On-time in-full (OTIF) | receipts matched against PO promise date and quantity | requires the receipt↔PO line join, which is the usual missing link |
| Claim-to-spend ratio | claim cost value ÷ supplier invoice value | needs a QA or complaint source |
| Price variance | invoice price − PO price, per line | pure ERP, always computable where invoices are connected |
| Lead-time variability | spread of promise-to-receipt, not the mean | the mean is a vanity metric; the spread is what drives buffer stock |

**Target notes.** Peer comparison is the natural target here (supplier X vs. supplier Y for the same material), and it is available without any plan data. This makes Supply the dimension that looks best earliest.

**Allocation notes.** Delay cost and claim cost must be allocated to a supplier through an explicit rule. Buffer-stock cost attributable to lead-time variability is the hard case and should ship as a named optional scheme, not as a default.

**Simulation levers.** Price, timing (lead time), volume (dual-sourcing shift as a mix lever), rate (defect rate).

**Data availability. This is the gap.** RelBench has no procurement dataset. CTU has none at scale. AdventureWorks is the best available and is genuinely useful — Vendor, PurchaseOrderHeader, PurchaseOrderDetail, ProductVendor, ship method, promise dates and invoice prices — which supports price variance, a workable OTIF, and lead-time variability. It has **no claims and no QA layer**, which is roughly half the flagship metric. That layer must be synthesized, and the demo must say so out loud. Building a credible synthetic claim layer over AdventureWorks is a real work item, not a footnote.

---

## Capacity — "What you run on"

**Canonical entities.** Machine, line, cell, vehicle, site, warehouse, room/bed/seat, licence, role-hour pool · downtime event, maintenance order, shift calendar.

**Ladder.** Site → line → machine, or site → fleet → vehicle, or practice → grade → role-hour pool.

**Canonical unit metrics.**

| Metric | Definition | Notes |
| :---- | :---- | :---- |
| Cost per capacity hour | full cost ÷ available hours | the generalized unit; works for a machine, a truck, a room and a consultant grade |
| Utilization | used ÷ available, against a stated theoretical ceiling | the ceiling definition must be explicit and versioned; most disputes are about the denominator |
| Output per unit of capacity | throughput ÷ capacity unit | pairs with Offer's margin-per-constrained-resource |
| Mean time between failures | operating time ÷ downtime events | asset archetypes only |
| Maintenance cost index | maintenance order cost ÷ replacement value | catches run-to-failure economics |

**Target notes.** The theoretical ceiling is a target of a fourth kind — a *definitional* Soll rather than an estimated one. It should be typed distinctly so it is not confused with plan.

**Allocation notes.** Shared capacity across product groups is the allocation problem here, and it is the input to Offer's DB ladder. The two dimensions must reference one scheme, not two.

**Simulation levers.** Capacity (add a shift, add a line), rate (uptime, cycle rate), timing (maintenance interval).

**Data availability. Weak.** No public relational dataset carries machine downtime and maintenance orders with cost. CTU's SAT dataset is failure diagnosis without economics. This dimension needs either a design partner's data or a purpose-built synthetic generator. That is an argument for sequencing it after a pilot, not before.

---

## Throughput — "How work flows"

**Canonical entities.** Process step, work order, operation, shift, line, team, project, task, WIP position. **Never individual.**

**Ladder.** Value stream → process → step, with shift/team/project as categorical cross-cuts.

**Canonical unit metrics.**

| Metric | Definition | Notes |
| :---- | :---- | :---- |
| Cost per process step | allocated cost ÷ completed steps | the unit |
| Cycle-time efficiency | standard duration ÷ actual duration | needs a standard; where none exists, prior period substitutes |
| Yield / first-pass rate | good output ÷ total attempts | scrap and rework are the cost translation |
| Rework cost per unit | rework hours × rate ÷ good units | the metric that turns a quality conversation into a money conversation |
| Utilization × realization (people archetype) | billable ÷ available, invoiced ÷ billable | must be computed at grade or team level, never person |
| Cost at completion vs. plan (project archetype) | earned value against booked cost | project archetype's binding metric |

**Compliance notes.** Person-level bindings are quarantined by default (§87 BetrVG, GDPR — see RFC 0). The workaround that keeps this dimension useful for the people-intensive archetype is aggregation to **role, grade, team or project**, which preserves every metric an executive actually acts on and removes every metric a works council would object to. This is not a degraded mode; state it as the design.

**Target notes.** Standards are the natural target where they exist (routings, standard times). Where they do not, peer comparison across lines or teams is stronger than prior period.

**Simulation levers.** Rate (yield, cycle time), capacity (shift structure), timing (sequencing, batch size).

**Data availability. Weak, and compliance-constrained even where data exists.** Public manufacturing execution data with cost is effectively unavailable. Synthetic generation is the realistic path.

---

## Capital — "Where your cash sits"

**Canonical entities.** Inventory position, stock movement, receivable, payable, work in progress, capex item, asset register entry, credit line.

**Ladder.** Total working capital → component (inventory / receivables / payables) → entity (SKU, customer, supplier) → item.

**Canonical unit metrics.**

| Metric | Definition | Notes |
| :---- | :---- | :---- |
| Cash conversion cycle | DIO + DSO − DPO | the anchor metric; decomposable down the ladder |
| Days inventory by SKU / group | inventory ÷ COGS run rate | where dead stock becomes visible as money, not units |
| Days sales outstanding by customer | receivables ÷ revenue run rate | pairs directly with Demand's cost-to-serve to produce a true customer ranking |
| Days payable by supplier | payables ÷ spend run rate | pairs with Supply's effective cost — a cheap supplier on payment terms may be expensive on price |
| Capital per unit of output | capital employed ÷ output | the turnover term made operational |
| Inventory carrying cost | holding rate × average inventory value | the rate is an assumption; it must be a named, versioned parameter |

**Target notes.** Prior period is strong; peer comparison across SKUs and customers is strong; plan data almost never exists at this grain. Expect permanent *partial* on the plan branch and design for it.

**Allocation notes.** Little allocation, much attribution: assigning a receivable to a segment or an inventory position to a product group is a join, not a key choice. This makes Capital unusually cheap to light once the ledger and stock data are connected.

**Simulation levers.** Timing (terms, reorder point, batch size), volume, rate (carrying cost, service level).

**Data availability. Moderate.** CTU's Financial dataset gives loan and transaction structures; AdventureWorks carries inventory positions and purchase/sales flows sufficient to compute a real cash conversion cycle. rel-salt carries ledger data. This dimension is more buildable on public data than either Capacity or Throughput, which is worth weighing against its lower demo drama.

---

## Cross-dimension structure

The dimensions are entity dimensions; the interesting facts are their intersections. The compound queries that justify the whole model:

- **Supply × Demand** — did supplier claims cause order delays, and for which customers?
- **Supply × Capital** — is the cheapest supplier cheapest after payment terms and buffer stock?
- **Capacity × Throughput** — does one shift pattern produce more downtime than another, at team-level aggregation?
- **Offer × Capacity** — which product group earns most per hour of the binding constraint, rather than per unit sold?
- **Demand × Capital** — which customers are profitable on margin and unprofitable on cash?

Each of these is a single query in the unit-economics grammar once both dimensions are lit and one allocation scheme spans them. None of them is expressible in a standard BI semantic layer without hand-built modelling, which is the competitive point.

## Data availability summary

| Dimension | Public data | Best source | Gap |
| :---- | :---- | :---- | :---- |
| Demand | strong | rel-salt (real SAP), AdventureWorks, Northwind | none material |
| Offer | strong | AdventureWorks, rel-hm, ClassicModels | cost structure below DB1 is thin |
| Supply | **weak** | AdventureWorks purchasing | no claims, no QA — must synthesize |
| Capacity | **very weak** | none adequate | needs partner data or a generator |
| Throughput | **very weak** | none adequate | needs partner data or a generator |
| Capital | moderate | AdventureWorks, CTU Financial, rel-salt | carrying-cost parameters are assumptions |

The uncomfortable read: the dimension with the best flagship question (Supply) has the second-worst data situation, and the two dimensions with the most demo drama (Capacity, Throughput) have none. Sequencing in RFC 3 takes this seriously.
