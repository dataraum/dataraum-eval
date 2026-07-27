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

**Data availability. Strong, but watch the licence.** AdventureWorks OLTP (MIT) carries 31,465 sales orders, 121,317 lines and 19,820 customers — commercially clean and ready to restore. SAP SALT / rel-salt is real SAP sales data at 4.7M rows across four tables, but it is **CC-BY-NC-SA 4.0 and therefore cannot carry a commercial demo** — research and internal benchmarking only. Northwind and ClassicModels are structurally fine and too small to look serious. TPC-DS scales without limit if volume is the point.

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

**Data availability. Strong.** AdventureWorks carries 504 products with `StandardCost` and `ListPrice` plus full cost-history and price-history tables, so DB1 is real and DB2 is a defensible construction. Product hierarchies also exist in rel-hm and rel-amazon. Nothing public gives a genuine step-fixed cost layer; DB3 is synthetic everywhere.

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

**Data availability. Better than first assessed — this is no longer the gap.** Three sources, none of which requires inventing a claims layer:

- **BPI Challenge 2019** (4TU, **CC BY 4.0**) — 1,595,923 events across 251,734 purchase-order items and 76,349 purchase documents, with `Vendor`, `Vendor Name`, `Item Category`, `Spend area`, `Goods Receipt` flag, `GR-Based Inv. Verif.`, and a per-event `Cumulative net worth (EUR)`. The four matching flows (3-way after GR, 3-way before GR, 2-way, consignment) are explicit case attributes. This is a native purchase-to-pay corpus at credible scale under a clean licence. It is an event log, so relationalising it is a work item — but that is engineering, not fabrication.
- **AdventureWorks Purchasing** (MIT) — `PurchaseOrderDetail` carries `OrderQty`, `ReceivedQty` and **`RejectedQty`**: 563 of 8,845 lines have rejects, 3.12% of units received. That is a real quality signal, not a synthesized one. `ProductVendor` carries `AverageLeadTime`, `StandardPrice`, `LastReceiptCost`, `MinOrderQty`. Small (104 vendors, 4,012 POs) but complete in shape.
- **SCMS / USAID Supply Chain Shipment Pricing** (**CC-BY**) — 10,324 lines, 73 named vendors, 88 manufacturing sites, $1.63bn line value and $68.8m freight broken out separately, with `Scheduled Delivery Date` vs `Delivered to Client Date`. Measured OTD is 88.5% with a 27.2-day slip SD, and vendors genuinely separate (Mylan 99.4% vs. Aurobindo 85.9%). Caveats: `PO Sent to Vendor Date` is populated on only 4,592 rows, and the largest "vendor" is a distribution centre that must be relabelled.

For an **external** claim signal on SCMS, the openFDA drug enforcement API (public domain, 17,755 records) contains Aurobindo, Cipla, Mylan, Sun and Teva as `recalling_firm` — all SCMS vendors. A name match weighted by recall classification produces a real claim-to-spend ratio over real PO and delivery data. Coverage is partial (roughly a third of the vendor panel), which should be shown as coverage rather than papered over — which is, conveniently, the product's own register.

Not usable: DataCo Smart Supply Chain has **no vendor column at all** (all 53 checked) and slip bounded to −2…+4 integer days. Olist is the most complete single supplier-performance dataset in existence — 462 sellers with ≥50 delivered items, promise vs. actual dates, freight at 16.6% of merchandise spend, and a review score that degrades from 15.1% bad overall to 63.3% bad on late items — but it is **CC BY-NC-SA and cannot carry a commercial demo.** Public procurement (TED, USASpending, UK Contracts Finder) is real supplier spend at enormous scale but stops at award: no goods receipt, no delivery date.

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

**Data availability. Strong — this was the largest error in the first assessment.**

- **Cincinnati Fleet Services** (four linked tables, **public domain**, Socrata API, refreshed daily, 2008→present) is the find. 332,420 maintenance work orders carrying `labor_cost`, `parts_cost`, `total_cost`, `downtime_hrs_shop`, `downtime_hrs_user`, `delay_hours` and `labor_hours`; 818,903 asset-months carrying `fuel_cost`, `deprec_cost`, `pm_labor_hrs` and `fixed_monthly_cost`; an asset master with original and replacement cost; a procurement table. Joins on `eq_equip_no` with a parent-equipment hierarchy. **Every metric in this dimension exists as a literal column** — cost per capacity hour is `total_cost` over a meter delta, downtime cost is `downtime_hrs_*` × a rate derivable from the same table, maintenance cost index is PM vs. repair job type. No synthesis required anywhere.
- **UWA/NIST excavator maintenance work orders** (public domain, via `pip install nist-nestor`) — 5,485 real mining MWOs against 5 named excavators, 2001–2012, AUD 17.5m of actual spend, repair-vs-replace typed. Tiny and completely real; the cleanest possible maintenance-cost-index demo. No durations.
- **Hill of Towie wind farm** (Zenodo, **CC-BY-4.0**, 12.6 GB) — 21 named turbines, 10-minute SCADA 2016–2024, rated power in the static table as the utilization denominator and an explicit per-turbine shutdown-duration file as the numerator. The one open dataset where availability is measured rather than inferred from alarm codes. No cost.
- **AdventureWorks `Production.Location`** — 7 real work centres with `CostRate` (€12.25–25.00/hr) and `Availability` in hours. Toy scale, correct shape, MIT.
- **US BTS aviation** (public domain) — ~7M flights/year with real tail numbers, plus Form 41 P-5.2 quarterly operating expense by carrier × aircraft type. Utilization is per-asset and real; cost joins only at type level, so cost-per-block-hour is an allocation — which makes it an unusually honest showcase for the allocation machinery.

Rejected: AI4I 2020 and SECOM have no asset entity. NYC TLC contains no vehicle identifier in the current schema. C-MAPSS is simulated with no wall-clock time or cost.

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

**Data availability. Moderate — the shape exists, the money does not.**

- **AdventureWorks Production** (MIT) is far richer than first assessed. `Production.WorkOrder`: 72,591 rows with `OrderQty`, **`ScrappedQty`**, `StockedQty`, `StartDate`/`EndDate`/`DueDate`, `ScrapReasonID` against a 16-row reason table. `Production.WorkOrderRouting`: 67,131 operations with `ScheduledStartDate`/`ScheduledEndDate` vs `ActualStartDate`/`ActualEndDate`, `ActualResourceHrs` and `LocationID`. Schedule variance is genuine — 58.4% of operations deviate from schedule and 31.4% of work orders finish late. Scrap is real but sparse (0.24% of units). **The one hard limit: `ActualCost` equals `PlannedCost` on 100% of 67,131 routing rows.** Cost variance is the single thing that must be synthesized, and it must be disclosed.
- **"Production Analysis with Process Mining Technology"** (4TU) is the only public log with true shop-floor vocabulary: `Work Order Qty`, `Qty Completed`, `Qty Rejected`, `Qty for MRB`, an explicit `Rework` column, `Span` as standard duration against actual start/complete, plus machine and worker resources. Every column in this dimension's spec maps to a real field. Two costs: only 225 cases, and no monetary attribute at all. Licence is "4TU General Terms of Use", not an open licence — needs a legal read before commercial use.
- **BPI Challenge 2012** (262,200 events) is the only log with a clean SCHEDULE → START → COMPLETE lifecycle, which is what separates queue time from touch time. Banking, not manufacturing, and same licence caveat.
- **BPI Challenge 2018** (**CC0**, 2.5M events) carries `amount_applied` vs `payment_actual` vs `penalty_amount` — structurally identical to standard-vs-actual variance, and the cleanest committed-vs-actual-vs-penalty triple in any open log.

Compliance note on the data itself: the 4TU Production log carries `Worker ID`. Any demo built on it must aggregate to resource or report type before display, which makes it a good public demonstration of the quarantine rule rather than a problem.

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

**Data availability. Moderate.** AdventureWorks carries 1,069 inventory positions across 14 locations and a 113,443-row costed `TransactionHistory` split across work orders (31,002), sales (74,575) and purchases (7,866) — a genuine three-source inventory ledger with `ActualCost` per movement, which is enough for days-inventory and capital-per-unit-of-output. **It has no AP subledger and no general ledger**, so DPO and a true working-capital statement are not computable; Capital there means inventory plus order values. Wide World Importers (MIT) is stronger on the receivables and payables side. CTU's Financial dataset gives loan and transaction structures. Carrying-cost rates are an assumption everywhere and must ship as named, versioned parameters.

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

Revised after a full source review. Licence is a column because it turned out to be the binding constraint, not content: the single most complete source for Supply (Olist) and the only real SAP sales corpus (rel-salt) are both **non-commercial** and therefore unusable in a demo, while several sources previously written off as absent are public domain.

| Dimension | Public data | Best commercially-usable source | Licence | Remaining gap |
| :---- | :---- | :---- | :---- | :---- |
| Demand | strong | AdventureWorks OLTP (31,465 orders / 19,820 customers) | MIT | rel-salt is **CC-BY-NC-SA — cannot carry a commercial demo** |
| Offer | strong | AdventureWorks (504 products, cost + price history) | MIT | cost structure below DB1 is thin; DB3 synthetic |
| Supply | **strong** | BPI Challenge 2019 (1.6M events, 251,734 PO items) + AdventureWorks `RejectedQty` + SCMS/USAID | CC BY 4.0 · MIT · CC-BY | XES → relational conversion; Olist blocked by NC licence |
| Capacity | **strong** | Cincinnati Fleet Services (332,420 WOs, 818,903 asset-months, every cost a literal column) | public domain | vocabulary is fleet, not factory; needs relabelling for other archetypes |
| Throughput | moderate | AdventureWorks `WorkOrder` + `WorkOrderRouting` (72,591 / 67,131 rows) · BPI 2018 | MIT · CC0 | **`ActualCost == PlannedCost` on 100% of routing rows — cost variance must be synthesized and disclosed** |
| Capital | moderate | AdventureWorks inventory + 113,443-row costed `TransactionHistory` | MIT | no AP subledger, no GL → DPO not computable; carrying-cost rates are named assumptions |

Two corrections to the first assessment, both material. **Supply is not the gap** — BPI 2019 is a native, openly licensed purchase-to-pay corpus with vendor, goods receipt, invoice, EUR value and explicit three-way-match flows, and AdventureWorks `PurchaseOrderDetail.RejectedQty` (563 lines, 3.12% of units) is a real quality signal rather than a synthesized one. **Capacity is not "very weak"** — Cincinnati Fleet Services carries `labor_cost`, `parts_cost`, `total_cost`, `downtime_hrs_shop`, `downtime_hrs_user`, `fuel_cost` and `deprec_cost` as literal public-domain columns joined on one asset key, so every metric in the Capacity spec is computable with no synthesis at all.

What remains genuinely hard is narrower than it looked: **cost variance inside Throughput** (the only figure that must be invented), **DPO and the working-capital statement** (no open source has an AP subledger), and **cross-dimension coherence** — no single open corpus spans Demand, Supply, Capacity and Capital for one firm, which is a stitching problem, not a scarcity problem. RFC 4 addresses it.
