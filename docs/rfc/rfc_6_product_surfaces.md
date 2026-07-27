# RFC 6 — Where the dimensions land in the product

*Status: golden (new — the drafts had no product-surface part) · Part 6 of 6*
*Read with RFC 0 (the model) and RFC 3 (the order). This is the "where does it actually show up" doc.*

---

## Why this part exists

RFC 0–4 imagine one delivery point for the dimension model: a coverage map, after a
pipeline run. The product has **five** places where a dimension prior does work, four of
them earlier than that, and all five already exist as surfaces. Designing the dimension
model without them under-uses the product and re-invents mechanisms that ship today.

The chain a customer actually walks: **connect → probe → stage → frame → run → answer →
drill → teach → report.**

## 1. Acquisition — probe, staging hub, recipes

A database source is a **recipe**: a backend plus named SELECTs materialized into raw
tables, stored on the source row's `connection_config['tables']` and synthesized by the
cockpit (the YAML recipe format is gone; DAT-430). Credentials resolve at extraction time
from `DATARAUM_<NAME>_URL`. Backends reach DuckDB through ATTACH extensions — mssql,
postgres, mysql, sqlite.

*Naming correction (2026-07-27 code read): "recipe" exists today only as the internal
DB-source connection loader (`sources/db_recipe/`), not as any user-facing surface. The
starter recipes below are therefore **new authored content** feeding an existing
mechanism — still small, but authored, not surfaced-from-existing.*

The staging hub assembles a heterogeneous import set (probed queries + files), sniffs each
item — `probeDescribe` for a query, the file sniff for a file — and unions them into **one
synthetic `ConnectSchema`**.

**Dimension delivery point #1 — the prior proposes the recipe.** "Which of the customer's
600 ERP tables do we pull?" is today an unaided human decision at the staging hub. A
dimension prior answers it directly: *Supply needs vendor, PO header, PO line, goods
receipt, supplier invoice.* That is a starter recipe per dimension — a concrete, small
artifact, authored once per backend family, and the most under-rated use of the whole
dimension model.

**And it makes a first meeting possible with no ingestion at all.** The staging schema
exists before any pipeline runs, so a *provisional* coverage map — which dimensions this
schema could carry — is computable at probe time from table and column names alone. It is
a weaker claim than the post-run map (structure, not grounding) and must be labelled as
such, but "here is what your database can and cannot tell you about your operating model,
computed in the first ten minutes" is the demo the RFC 4 discussion was reaching for.

## 2. Frame — where a vertical is born, and where the priors belong

`frame` runs induction over the staging schema + samples, in the cockpit, co-designing the
model with the user, and writes it to the engine-owned schema: concepts and conventions to
their typed tables, validations / cycles / metrics through the teach seam. It frames the
**whole model in one call**, four families, each with two paths:

- **induce** — the LLM proposes the family's set over the same-call concepts;
- **declare** — an edited set is written verbatim, no LLM. This is the accept/edit
  round-trip of the ModelFrame widget.

Two facts here are decisive for the dimension model.

**(a) Induction is seeded with structural few-shot from the nearest shipped vertical — and
that is a known leak.** Cycles and metrics seed from the nearest shipped vertical;
validations deliberately do **not**, because (DAT-725 band 3) *a finance few-shot example
IS finance vocabulary, and leaking it into another vertical's induction is exactly the
cross-vertical leakage to avoid*. So induction currently has a choice between a leaky seed
and no seed.

> **The six dimensions are precisely the seed library that is missing.** Demand, Offer,
> Supply, Capacity, Throughput and Capital are vertical-neutral by construction — they are
> the cross-industry spine, not one industry's vocabulary. Seeding induction with dimension
> priors instead of with the nearest shipped vertical solves the leakage problem *and*
> gives the dimension model its delivery vehicle. This is the highest-leverage placement in
> the entire program and it needs no new surface.

*Cost correction (2026-07-27 code read): cheaper than it reads.* The seed reader is an
injectable parameter — `nearestSeedVertical` / `readSeed` in
`packages/cockpit/src/tools/frame-family.ts` — so swapping in the dimension priors is a
parameter change plus authored content (DAT-885), not a rewrite. And the leak is 2/3
families by explicit ruling, not an unexamined bug: validations were de-seeded under
DAT-725 band 3; cycles and metrics still seed from finance because no leakage concern was
raised for them at the time.

**(b) A framed vertical must acquire executable knowledge, not just concepts.** Lead
mandate on DAT-855 strand 2: *a frame-declared or generated vertical MUST acquire
validations, cycles and metrics, authored in collaboration with the user*; a data-analytics
workspace without them is wrong, and the engine's `nothing_declared` terminal state is
transitional handling of an invalid state, never a valid end state.

That is the same requirement the dimension model imposes from the other direction: a
dimension is only real when its **unit metrics** exist, and metrics are one of the four
frame families. The dimension prior ships a metric template set per dimension; induction
proposes the subset the schema supports; the user edits; `declare` writes it. The
coverage map then reads what was declared.

## 3. The answer agent — where "compared to what" becomes visible

`answer` is a nested sub-agent with its own tools (`snippet_search` over the validated
snippet library, `run_steps` to validate SQL). It composes an answer as **concept-named
steps plus a combining final SQL**, reuses validated snippets classified as
exact_reuse / adapted / fresh, validates the composed CTE statement, captures it, reads a
bounded headline, and hands the *same captured statement* to the browser for the full
result — so the number stated and the grid streamed are provably the same query.

Two properties matter for RFC 1:

- **The data-quality band already rides along as information, never a filter.** Gating was
  deliberately removed. The target operator's disclosure — *which target, why not the
  others, how wide the band* — belongs on exactly this seam: an annotation on the answer,
  not a gate in front of it.
- **Answers are composed from concept-named steps.** A target is a step. "Prior period",
  "peer median", "plan" are steps composable beside the measure step, in the same CTE, with
  the same validation and the same grid handle. The target operator is therefore not a new
  subsystem in the answer path — it is a step kind plus a resolution rule.

**Its future is already the deviation product.** DAT-855 strand 1: repurpose the answer
direction toward **root-cause narratives — drivers + drill + validation evidence composed
into "why", not just "what"**, with the driver teach (DAT-549) and on-demand driver
discovery (DAT-573) as its concrete tails. "Why is cost-to-serve up in channel B" is that
strand with a unit metric and a target attached. The dimension work does not need a new
answer surface; it needs to arrive in time to shape that one.

## 4. Drill and the result grid — the granularity ladder

The shared result grid plus the drill composition path (`/api/drill/axes`, `/compose`,
`/node`) is RFC 0's granularity ladder, already mounted from the model canvas and being
extended to answers, `run_sql` grids and report detail. Axes come from metadata the engine
already computes — slice definitions, driver rankings, dimension hierarchies. Drill
composes upstream of the grid as a new effective base SQL; persistence is *steps, not SQL*.

The dimension model contributes one thing here: the ladder per dimension (RFC 2) is the
declaration of which descent paths are meaningful, which is exactly what the axis catalog
work (DAT-879: relevance score, honest caps, non-categorical axes) needs as a prior.

## 5. Model canvas, teach, reports

- **The operating-model canvas** is where the coverage map belongs — it already renders the
  recovered model, and the map is a grouping of it by facet.
- **Teach** is the correction loop for every layer the dimensions touch: concept binding,
  metric, cycle, validation, unit, relationship. A wrong dimension binding is a teach, not
  a bug report — and teach closure is already a graded property for five teach types.
- **Reports** mint durable widgets from answers, with drilled results becoming child
  reports. A dimension's flagship metric with its target and band is a report; the coverage
  map's dark branches are the report catalog's backlog.

## Where each RFC concept lands

| Concept | Surface that carries it | Status |
| :---- | :---- | :---- |
| Dimension prior → which tables to pull | staging hub / recipe authoring | surface exists; starter recipes are new, small |
| Provisional coverage map (structure only) | staging hub, pre-ingestion | computable from the staging schema today |
| Dimension prior → induction seed | `frame` (concepts + metrics + cycles + validations) | **the placement to take**; replaces a leaky vertical seed |
| Unit metrics per dimension | frame metric family → engine metric graph | needs extract predicates (DAT-838) |
| Granularity ladder | shared result grid + drill | in flight (DAT-671, DAT-879) |
| Target + band + "why not the others" | answer agent step + the existing band annotation | new; rides an existing seam |
| Deviation → why | answer agent root-causing | DAT-855 strand 1, not started |
| Coverage map (post-run) | operating-model canvas | new read over existing rows |
| Corrections | teach | exists for every relevant layer |
| Vertical as an ontology graph | DAT-855 strand 3 | the lead's own direction; the dimension facet is its content |

## Consequence for the roadmap

Three of the five delivery points (**recipe priors, induction seeds, coverage map**) are
additive: they consume schema and metadata that already exist and change no engine
behaviour. They can be built and demonstrated **without waiting for the grammar work** in
RFC 3 lane B1 — what they cannot do until then is *grade* a number.

That is the split that keeps the performance-analytics move moving: **the dimension model
ships as priors and surfaces immediately; the claims it makes about numbers ripen as the
grammar and the pipeline-error measurement land.**
