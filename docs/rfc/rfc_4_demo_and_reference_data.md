# RFC 4 — Demo and reference data

*Status: golden (grounded 2026-07-27) · Part 4 of 6*
*Answers: how do we demonstrate dimensions whose data we cannot show, and where does the demo corpus overlap the test corpus? Depends on RFC 2. Feeds RFC 3 and the design-partnership agreement.*

---

## The conundrum, stated precisely

Two constraints that look like they close the door on each other:

1. **Partner data cannot be shown.** Whatever a design partner connects is their
   confidential operating data. It cannot appear in a demo, a screenshot, a talk or a
   website. This does not soften with a good relationship.
2. **No single public corpus spans the model.** Per-dimension public data may be better
   than first assessed, but there is no open dataset covering Demand, Offer, Supply,
   Capacity, Throughput and Capital *for one firm* — and the cross-dimension compound
   queries are precisely what no competitor can answer.

The apparent conclusion — "we need partner data to demo, and we cannot use partner data" —
is false, because "demo" is four different jobs collapsed into one word.

## Splitting the word "demo"

| Job | What it must be | Data answer | Realism required |
| :---- | :---- | :---- | :---- |
| **A — First meeting** | a prospect watching the product recover a model and answer a question | the reference company | plausible and *coherent*; not true |
| **B — Proof of fit** | the prospect believing it works on *their* reality | their own data, in their perimeter | total — it is their data |
| **C — Engineering fixtures** | graded regression tests for binding, allocation, targets, forecasting | Tier A (generated, full truth) + Tier B (wild, structural truth) | high, including the ugly parts — **and it needs an answer key** |
| **D — Marketing surface** | screenshots, site, deck, talks | the reference company only | low; legal clearance is the binding constraint |

Only **C** needs data that behaves like reality under stress *and* has a known correct
answer. Only **B** needs the partner's actual rows, and there the answer is not to extract
anything. **A** and **D** need *coherence*, not truth: one firm, one calendar, joined keys,
believable magnitudes, a question that resolves.

## The one design change from the draft: generate, don't stitch

The draft builds the reference company as a **stitch** of five open corpora — AdventureWorks
as spine, BPI 2019 keys remapped onto its vendors, Cincinnati's fleet structure remapped to
work centres. That produces a coherent demo and **no answer key**: you cannot state the true
DB2 of a fictional firm assembled from someone else's rows. So the stitched company can
serve jobs A and D and can never serve job C — and a demo corpus that cannot be graded will
drift away from the tested corpus until they are two different products.

**Build the reference company the way the corpus policy already prescribes: replicate a
documented real backend schema and generate values into it.** `entropy_eval_architecture.md`
states the rule for any new domain — *"replicates a documented real backend system
(ERP/CRM/billing/POS export shapes) with synthetic values generated into the borrowed
schema, so ground truth stays computable."*

Same spine (AdventureWorks is a documented, MIT-licensed, single-firm ERP schema covering
customers, products, purchasing, work orders and inventory), same vocabulary, same demo —
plus:

- **an answer key**, so every demo number is also a graded fixture;
- **injection families**, so the demo corpus can also carry the defects we detect;
- **no licence surface at all** on the rows, because we generated them;
- **one corpus for jobs A, C and D**, which is what keeps the demo honest over time.

Where public rows are genuinely better than generated ones — messy real distributions,
real exception rates — they stay **Tier B**: run against them, score the structural
scoreboard, and use what they reveal to improve the generator. That is the existing
authenticity loop, not a new mechanism.

**To be clear about what "borrowed" buys and does not constrain.** Borrowing a documented
schema buys realism and keeps us from grading ourselves on a world we invented top to
bottom; it is a rule about the *provenance of the shape*, not permission to generate. Where
no documented open schema fits — Capacity and Throughput across several archetypes are the
likely cases — designing the schema ourselves is legitimate, provided the shape is checked
against a real system we can read (a partner's, at rights level 2) or against a wild corpus
in the same family. The failure mode to avoid is a corpus that is *both* invented and
unchecked; the answer is the check, not abstinence.

## What we extract from a partner: the shape

The asset a design partner gives us is not rows. It is **shape**, and shape is not
confidential the way rows are:

- schema and join topology — which tables exist, which keys connect, which are optional
- cardinalities and fan-out ratios — orders per customer, lines per order, receipts per PO
- metric definitions as the company computes them — what *they* mean by OTIF, utilization, DB2
- marginal distributions and their tails — order value, lead time, downtime duration, scrap rate
- correlation and seasonality structure
- exception rates — how often a three-way match fails, how often an operation is re-run
- vocabulary — what the fields are *called*, which is most of what makes a demo feel native

Everything on that list is a parameter. **Only parameters cross the partner perimeter**,
each reviewable line by line. That is a conversation a partner can say yes to; "can we show
your numbers" is not.

This has a precedent in the codebase: `schema_transforms.py` already parameterizes the
synthetic corpus by normalization level, column style and key strategy. Partner shape
parameters extend that layer; they do not invent one.

Two immediate uses: it tells us which dimension the *archetype prior* should weight (real
evidence rather than a guess), and it lets us regenerate the reference company at the right
shape without carrying a single real row.

## Three tiers, one hard line

**Tier 0 — Open corpora, used as Tier B.** Public, licence-audited, cited by name. Their
job is falsification and realism feedback, never certification: wild data has structural
truth only (declared FKs, types, time columns), so a wild run can prove a detector wrong
and can never prove a metric right. NC-licensed corpora (rel-salt, Olist) are internal-use
only — fetched at run time, never committed, never in a commercial demo. **Licence is
audited per dataset and recorded**; a dataset without a recorded licence does not enter the
demo path.

**Tier 1 — Generated into a borrowed schema (this is Tier A).** Rows generated from a
documented real schema and from partner *shape parameters*, never from partner rows.
Preserves join topology, cardinalities, distributions, seasonality and exception rates;
contains no real entity, quantity or price; **carries ground truth**. Every table carries a
provenance stamp naming its generator and its parameter source.

**Tier 2 — Partner data, in the partner's perimeter, never extracted.** For job B, the
honest move is to run the product where the data already is. This is available to us and
rarely to competitors, because the product's claim is that it recovers a model from data
rather than requiring modelling first.

The line between Tier 1 and Tier 2 is absolute: **no row that originated in a partner
system is ever rendered outside that partner's tenant.** Not anonymized, not aggregated,
not "just for this one slide". Only parameters, only under the clause below.

## The reference company

One fictional firm, one calendar, one set of keys, on the AdventureWorks schema shape:
customers and orders (Demand), products with cost and price history (Offer), vendors and
purchase orders (Supply), work centres and work orders (Capacity, Throughput), inventory
and costed transactions (Capital).

Dimensions light up as their generator families land (RFC 3), and the coverage map shows
the rest dark — which is the honest and the better demo.

### The seams are the demo, not the embarrassment

A dataset with mixed provenance would be a liability for a tool that presents numbers as
facts. For this product it is the argument. The coverage map already displays provenance
and confidence; the honesty register already types a figure as ready / investigate /
blocked. **The reference company ships with its own provenance ledger, rendered in the
product's own surface** — this figure is measured, this one derived, this one generated and
here is its generator.

A prospect who asks "is this real data?" gets an answer no competitor can give: *here is
exactly which parts are, and the product is what is telling you.* Demoing the disclosure
mechanism on the demo data itself is a stronger proof than clean fake numbers ever are.

Corollary, and it is a hard rule: **no unlabelled synthetic figure ever appears in a demo
or a screenshot.** One caught fabrication costs more than every dimension the fabrication
was covering for.

## Demo-rights clause for the design-partnership agreement

A rights ladder, asked for as four separately grantable levels rather than one
all-or-nothing permission. Partners refuse blanket asks and routinely grant staged ones.

1. **Nothing leaves.** Default and always available. We run inside their perimeter; we take
   away learnings, no artifacts.
2. **Shape parameters leave, on review.** Schema, cardinalities, distributions, exception
   rates, metric definitions — enumerated, shown, approved item by item, used only to
   generate Tier 1 data. This is the level that unblocks the roadmap and the one to secure
   at signing.
3. **Anonymized derivative, named review.** A generated dataset built from their shape,
   signed off before any external use, with a right of withdrawal.
4. **Named reference.** Logo, case study, quantified outcome, joint talk. Ask after value is
   demonstrated, never at signing.

Two supporting terms worth writing in now: a **publication-review window**, and an explicit
statement that **level 2 grants no rights to their rows** — which is what makes level 2 easy
to sign.

## Why the AI-training-data boom did not solve this

The training-data explosion produced text, images, code, and single-table tabular
benchmarks with labels. What this product needs is different in kind: **multi-table
operating data with join topology, money attached, and a time axis** — exactly the data
that carries a firm's competitive and personal-data exposure, and therefore exactly the
data nobody publishes. The exceptions are structural: process-mining research corpora,
public-sector transparency mandates, and vendor sample databases. Those three are the
entire supply. Our own shelf today is seven RelBench databases plus one FD-truth corpus.

Which is the deeper argument for generating: the corpus we need does not exist and will not
appear, and the one thing we can build that nobody else has is a multi-dimension operating
corpus **with an answer key**.

## Near-term implications

- **Decided 2026-07-27 ("yes, also my understanding"): reference company v0 is the
  existing finance corpus extended in place** with the operating chain (DAT-884) — one
  corpus carrying ledger truth, operating truth, demo and fixtures. AdventureWorks remains
  the *shape reference* for borrowed families (and an optional later full-schema
  replication if demo realism demands it), not a separate corpus build. The provenance
  ledger ships from day one rather than retrofitted.
- Put the licence audit in the build, not in someone's memory.
- Add level 2 of the rights ladder to the design-partnership agreement before the next
  partner conversation.
- For first meetings, prefer **onboarding over demoing** wherever a prospect can supply an
  export. The differentiator is what happens in the first hour on unfamiliar data; a canned
  demo hides it.
- Where a figure must be synthesized without a real basis (Throughput cost variance is the
  known case), make its disclosure a scripted demo beat rather than a footnote.

## Open questions

- Does the reference company get a name and an industry story, or stay explicitly a
  generated composite? Probably named, with the generation disclosed in the product's own
  provenance surface.
- How many archetypes does it need? One firm cannot be asset-intensive and
  contract-intensive at once. Likely a second, lighter reference for the services archetype
  once the first is stable.
- Do we publish the reference company and its generator? Open-core argues yes, and a
  well-built multi-dimension corpus **with ground truth** under an open licence would be a
  genuine contribution to a space that has none. It also hands competitors a demo. Defer,
  but not forever.
- What is the shortest path to an AP subledger and a general ledger for Capital — Wide World
  Importers as the borrowed schema, a partner at level 2, or generated? Decide before
  the Capital step (RFC 3, B6).
