# RFC 4 — Demo and reference data strategy

*Status: draft · Part 4 of 4 · Answers: how do we demonstrate Capacity, Throughput and Supply when partner data can never be shown?*
*Depends on RFC 2 (what data exists). Feeds RFC 3 (sequencing) and the design-partnership agreement.*

---

## The conundrum, stated precisely

Two constraints that look like they close the door on each other:

1. **Partner data cannot be shown.** Whatever a design partner connects is their confidential operating data. It cannot appear in a sales demo, a screenshot, a conference talk or a website. This does not soften with a good relationship, and asking for an exception at the wrong moment costs the relationship.
2. **No single public corpus spans the model.** RFC 2 established that per-dimension data is much better than first assessed — Supply and Capacity in particular are well covered under commercially usable licences. But there is no open dataset that covers Demand, Offer, Supply, Capacity, Throughput and Capital *for one firm*, and the cross-dimension compound queries are precisely the thing no competitor can answer.

The apparent conclusion — "we need partner data to demo, and we cannot use partner data" — is false, and it is false because "demo" is four different jobs that have been collapsed into one word.

## Splitting the word "demo"

| Job | What it must be | Data answer | Realism required |
| :---- | :---- | :---- | :---- |
| **A — First meeting** | a prospect watching the product recover a model and answer a question | reference company (below) | plausible and *coherent*; not true |
| **B — Proof of fit** | the prospect believing it works on *their* reality | their own data, in their perimeter | total — it is their data |
| **C — Engineering fixtures** | regression tests for binding, allocation, forecasting | messy real corpora + generated edge cases | high, including the ugly parts |
| **D — Marketing surface** | screenshots, site, deck, talks | reference company only | low; legal clearance is the binding constraint |

Only **C** needs data that behaves like reality under stress, and it never leaves the build system. Only **B** needs the partner's actual rows, and there the answer is not to extract anything — see below. **A** and **D**, the two jobs people mean when they say "we can't demo without partner data", need *coherence*, not truth: one firm, one calendar, joined keys, believable magnitudes, a question that resolves.

That reframing is the whole answer. The rest is execution.

## What we actually extract from a partner: the shape

The asset a design partner gives us is not rows. It is **shape**, and shape is not confidential in the way rows are:

- schema and join topology — which tables exist, which keys connect them, which are optional
- cardinalities and fan-out ratios — orders per customer, lines per order, receipts per PO, operations per work order
- metric definitions as the company actually computes them — what *they* mean by OTIF, utilization, DB2
- marginal distributions and their tails — order value, lead time, downtime duration, scrap rate
- correlation and seasonality structure — the fact that late deliveries cluster with one vendor and one quarter
- exception rates — how often a three-way match fails, how often a routing operation is re-run
- vocabulary — what the fields are *called*, which is most of what makes a demo feel native

Everything on that list is a parameter. **Only parameters cross the partner perimeter**, and each one is reviewable line by line before it does. That is a conversation a partner can say yes to; "can we show your numbers" is not.

Two immediate uses. First, it tells us which dimension the *archetype prior* should weight — real evidence rather than a guess. Second, it lets us regenerate the demo at the right shape without carrying a single real row.

## Three tiers of demo data, with a hard line between them

**Tier 0 — Open corpora.** Public, commercially licensed, cited by name in the demo itself. RFC 2 lists them: AdventureWorks (MIT), BPI Challenge 2019 (CC BY 4.0), BPI 2018 (CC0), Cincinnati Fleet Services (public domain), SCMS/USAID (CC-BY), openFDA (public domain), Hill of Towie (CC-BY-4.0), US BTS and NIST (public domain). Excluded on licence, not on quality: **rel-salt (CC-BY-NC-SA)** and **Olist (CC BY-NC-SA)** — both non-commercial, both otherwise the best in their category. This is a permanent rule, not a one-off check: licence is audited per dataset and recorded.

**Tier 1 — Structure-preserving synthesis.** Rows generated from Tier 0 corpora and from partner *shape parameters*, never from partner rows. Preserves join topology, cardinalities, distributions, seasonality and exception rates; contains no real entity, no real quantity, no real price. Every Tier 1 table carries a provenance stamp naming its generator and its parameter source.

**Tier 2 — Partner data, in the partner's perimeter, never extracted.** For job B, the honest move is not to take data out but to run the product where the data already is. This is available to us and rarely to competitors, because the product's own claim is that it recovers a model from data rather than requiring modelling first.

The line between Tier 1 and Tier 2 is absolute: **no row that originated in a partner system is ever rendered outside that partner's tenant.** Not anonymized, not aggregated, not "just for this one slide". Aggregate figures are extractable only under an explicit clause (below), and only as parameters.

## The reference company

One fictional firm, six lit dimensions, one calendar, one set of keys. Built as an explicit stitching job on Tier 0 corpora with the seams disclosed:

| Dimension | Source | Treatment |
| :---- | :---- | :---- |
| Demand, Offer | AdventureWorks OLTP | as-is; it is the spine because it alone spans customers, products, purchasing, work orders and inventory for one firm |
| Supply | AdventureWorks purchasing (real `RejectedQty`) + BPI 2019 event structure | BPI 2019 supplies the purchase-to-pay lifecycle and matching-exception rates; keys remapped onto the spine's vendors |
| Capacity | Cincinnati Fleet Services structure, remapped to work centres | real cost, downtime and depreciation *shape*; the spine's `Production.Location` supplies the vocabulary |
| Throughput | AdventureWorks `WorkOrder` + `WorkOrderRouting` | schedule variance and scrap are real; **cost variance is Tier 1 and labelled as such** |
| Capital | AdventureWorks inventory + costed `TransactionHistory` | real; days-payable is Tier 1 pending an AP subledger |

The spine choice matters more than any individual source: AdventureWorks is the only open corpus with one firm's customers, products, suppliers, work orders and stock under one licence, which makes the cross-dimension compound queries in RFC 2 demonstrable rather than merely describable.

### The seams are the demo, not the embarrassment

A stitched dataset with mixed provenance would be a liability for a tool that presents numbers as facts. For this product it is the argument. The coverage map already displays provenance and confidence; the honesty register already types a figure as ready / investigate / blocked. **The reference company ships with its own provenance ledger, rendered in the product's own surface** — this figure is measured, this one is derived, this one is generated and here is its generator.

A prospect who asks "is this real data?" gets an answer no competitor can give: *here is exactly which parts are, and the product is what is telling you.* Demoing the disclosure mechanism on the demo data itself is a stronger proof than clean fake numbers ever are.

Corollary, and it is a hard rule: **no unlabelled synthetic figure ever appears in a demo or a screenshot.** One caught fabrication costs more than every dimension the fabrication was covering for.

## Demo-rights clause for the design-partnership agreement

The existing agreement needs a rights ladder, asked for as four separately grantable levels rather than one all-or-nothing permission. Partners refuse blanket asks and routinely grant staged ones.

1. **Nothing leaves.** Default and always available. We run inside their perimeter; we take away learnings, no artifacts.
2. **Shape parameters leave, on review.** Schema, cardinalities, distributions, exception rates, metric definitions — enumerated, shown to them, approved item by item, used only to generate Tier 1 data. This is the level that unblocks the roadmap, and it is the one to secure at signing.
3. **Anonymized derivative, named review.** A generated dataset built from their shape, reviewed and signed off by them before any external use, with a right of withdrawal.
4. **Named reference.** Logo, case study, quantified outcome, joint talk. Ask after value is demonstrated, never at signing.

Two supporting terms worth writing in now: a **publication-review window** (they see anything derived from their engagement before it goes out) and an explicit statement that **level 2 grants no rights to their rows**, which is what makes level 2 easy to sign.

## Why the AI-training-data boom did not solve this

Worth stating because the intuition is reasonable and the conclusion is not. The training-data explosion produced text, images, code, and single-table tabular benchmarks with labels. What this product needs is different in kind: **multi-table operating data with join topology, money attached, and a time axis** — which is exactly the data that carries a firm's competitive and personal-data exposure, and therefore exactly the data nobody publishes. The exceptions are structural: process-mining research (the BPI logs), public-sector transparency mandates (Cincinnati, BTS, openFDA, SCMS), and vendor sample databases (AdventureWorks, Wide World Importers). Those three sources are the entire supply, and RFC 2 has now enumerated them. There is no fourth pile waiting to be found — but the three that exist turned out to be enough for five of six dimensions.

## What this implies for the near term

- Build the reference company on the AdventureWorks spine, with the provenance ledger from day one rather than retrofitted.
- Put the licence audit in the build, not in someone's memory. A dataset without a recorded licence does not enter the demo path.
- Add level 2 of the rights ladder to the design-partnership agreement before the next partner conversation, not after.
- For first meetings, prefer **onboarding over demoing** wherever a prospect can supply an export. The product's differentiator is what happens in the first hour on unfamiliar data; a canned demo actively hides it.
- Treat Throughput cost variance as the one disclosed synthesis in the whole demo, and make its disclosure a scripted demo beat rather than a footnote.

## Open questions

- Does the reference company get a name, a plausible industry story and a website presence, or does it stay explicitly labelled as a stitched public-data composite? The second is more honest; the first demos better. Probably: named, with the composite disclosed in the product's own provenance surface.
- How many archetypes does the reference company need? One firm cannot be asset-intensive and contract-intensive at once. Likely a second, lighter reference for the services archetype — Cincinnati's structure plus a consultancy vocabulary — once the first is stable.
- Do we publish the reference company and its generator? Open-core argues yes, and a well-built multi-dimension demo corpus under an open licence would be a genuine contribution to a space that has none. It also hands competitors a demo. Defer, but not forever.
- What is the shortest path to an AP subledger and a general ledger for Capital? Wide World Importers, a partner at level 2, or generated — decide before stage 5.
