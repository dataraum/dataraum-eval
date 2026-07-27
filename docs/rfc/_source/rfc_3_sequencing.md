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

The constraint that shapes this is not engineering effort — it is **data availability** (RFC 2). The dimension with the strongest flagship question has the weakest public data, and the two most demo-friendly dimensions have none at all. Sequencing that ignores this produces a roadmap that cannot be demonstrated.

### Stage 1 — Grammar before dimensions

**Forecast targets and deviation significance.** Applies to the finance ontology that already ships. Lights every *partial* branch without requiring a single new data source, and delivers the one line no competitor says: *this deviation is larger than the target's own uncertainty, and here is the target's track record*. Highest ratio of user-visible value to integration work anywhere in the roadmap, and it is dimension-independent.

Ship this first. It makes every subsequent dimension better on arrival.

### Stage 2 — Demand and Offer together

They share the granularity ladder, the DB ladder and the price–volume–mix bridge, and separating them means building the ladder twice. Both are buildable and demoable on **real** data today (rel-salt is genuine SAP sales and ledger data; AdventureWorks and Northwind cover the relational structure), which no other dimension can claim.

Flagship: the contribution-margin ladder per customer and per product group, with the allocation rule disclosed and two named schemes comparable side by side.

### Stage 3 — Capital

Cheapest remaining dimension to light: mostly attribution rather than allocation, computable from ledger and stock data that is already connected in stage 2, and it pairs immediately with Demand to produce the customer ranking nobody has — profitable on margin, unprofitable on cash. Lower demo drama, high executive resonance, low build cost. Take it while it is cheap.

### Stage 4 — Supply

The strongest flagship question in the whole model (*which supplier is really costing us money — price plus delays plus claims?*) and natively multi-source, which showcases the platform's actual differentiator. Held to fourth place only by data: AdventureWorks purchasing supports price variance, OTIF and lead-time variability, but carries no claims and no QA layer. Building a credible synthetic claim layer is a prerequisite work item, and the demo must disclose it.

If a design partner brings real procurement data with quality notifications, **Supply jumps to stage 2**. That is the single highest-value thing a partner can contribute, and it should be an explicit selection criterion in the design-partner search.

### Stage 5 — Capacity and Throughput

After pilot evidence, and after partner data exists. Neither has adequate public data; both would otherwise ship as synthetic-only, which is the wrong first impression for the two dimensions that produce the most impressive screens. Throughput additionally carries the compliance design (aggregate entities only), which is cheaper to get right once with a real works-council conversation behind it.

### Cross-cutting, prioritized by how often *partial* occurs in real pilots

- **Plan ingestion from spreadsheets.** Lights the plan branch everywhere. Legitimate first-class use of file import.
- **Projection** (forward what-if) on dimensions already lit and already allocated.
- **Goal-seek**, after projection is trusted. Inverting a model users do not yet believe is premature.
- **Scenario comparison surface** — side-by-side scenarios, side-by-side allocation schemes.

Ship one dimension at a time and let the coverage map carry the roadmap story honestly. "This dimension is coming" is a badge, not a promise.

## Data work items

| Item | Blocks | Effort |
| :---- | :---- | :---- |
| Synthetic claim / QA layer over AdventureWorks purchasing | Supply flagship metric | real, non-trivial |
| Carrying-cost and service-level parameter defaults | Capital simulation levers | small, but must be named and versioned |
| Capacity + Throughput synthetic generator | Stages 5 | large — argues for partner data instead |
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
