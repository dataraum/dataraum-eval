# The entropy system — architecture and state of the union

2026-06-11. Written for an engineering audience. Companion to
[`entropy_eval_architecture.md`](../entropy_eval_architecture.md) (the eval
method + measurement catalog); this document explains the **system**: where we
measure, who the witnesses are, which calls go to an LLM, what a user can
teach, and — honestly — where we actually stand.

## The idea in one paragraph

Entropy here means **disagreement about what the data means**, not statistical
noise. Every measurement is one of two shapes. A **scalar** is a single named
statistic — an orphan rate, a quarantine rate, a mutual-information score —
honest on its own, with nothing to argue about. An **adjudication** is a claim
("is `#ERR` a null marker?", "is `ending_balance` a stock or a flow?", "is
this column pair a real foreign key?") judged by several **independent
witnesses** — some read data, some read config, some are an LLM, some are a
human. Witness opinions are pooled, weighted by each witness's measured
reliability; the pool's **conflict** (witnesses disagree) and **ignorance**
(nobody has real evidence) are the entropy. Scores roll up through a per-intent
loss table into a per-column **ready / investigate / blocked** band — the thing
a practitioner actually sees. A **teach** is the closing move: a human answers
the contested question once, the answer lands in config, and on the next run
the conflict collapses. Nothing in the system overrides an LLM or a human with
a hard-coded rule; when a judgment is wrong, we fix the instruction or the
evidence it was given, and it judges again.

## Where we measure

Three measurement points, all terminal "detect" steps inside the Temporal
pipeline (`worker/activity.py` — a no-orphan guard asserts every phase that
declares detectors is covered by exactly one of these):

| Point | When it runs | What it measures |
|---|---|---|
| **add_source detect** | per uploaded table, after typing → statistics → temporal → per-column annotation | the column in isolation: `type_fidelity`, `null_ratio`, `null_semantics`, `business_meaning`, `unit_entropy`, `temporal_entropy`, `benford` |
| **session detect** | after a session composes its tables: relationship discovery, per-table semantics, lineage, enriched views, slicing, correlations | everything that needs more than one column or table: `relationship_entropy`, `relationship_discovery`, `join_path_determinism`, `dimension_coverage`, `dimensional_entropy`, `temporal_behavior`, `derived_value` |
| **operating_model detect** | after the validation phase of the operating-model workflow | `cross_table_consistency` — executed validation checks, scored; failed critical checks fan out to the exact columns the check read |

One boundary that matters and has bitten us twice: **relationship entropy
exists only on the defined catalog** — the pairs the LLM selector confirmed.
Before confirmation, candidate pairs are a deliberately generous structural
list (every column pair with enough value overlap). Candidates are input to the
selector, never a measurement surface.

## The witnesses, per adjudicated measurement

Reliability r is a witness's measured accuracy on labelled corpora the eval
repo generates (the rig). "Placeholder" = a stated prior, never tuned, waiting
for its measurement.

**null_semantics** — claim per quarantined token: *null-marker or genuine
value?*

| Witness | Reads | r |
|---|---|---|
| quarantine_clustering | data — does the token repeat/cluster like a sentinel? | **0.868 measured** |
| type_claim | data — the typing phase's view of the token | **0.266 measured** (weak by design finding: it can't tell a sentinel from a genuine unparseable — correctly down-weighted) |
| null_vocabulary | config — the vertical's curated null list | **0.944 measured** |

**temporal_behavior** — claim per measure column: *stock (point-in-time level)
or flow (per-period movement)?* Summing a stock across periods is silently
wrong money.

| Witness | Reads | r |
|---|---|---|
| ontology_prior | config — the bound concept's declared behavior | **0.762 measured** (faithful blend incl. ambiguous names) |
| llm_claim | LLM — reads the column name in context | **0.838 measured** (same blend) |
| structural_reconciliation | data — do per-period sums of an events table reconcile to the column's deltas? Pure arithmetic over the slice substrate | **0.889 measured** (events-backed corpus; small n=7 — widen before treating as final) |

**relationship_discovery** — claim per *confirmed* pair: *genuine or
spurious?*

| Witness | Reads | r |
|---|---|---|
| value_overlap | data — containment/overlap statistics of the pair | **0.923 measured in contract** (post-fix re-run; small n=11) |
| llm_judgment | LLM — the selector's confirmation confidence | **0.923 measured in contract** (conditional on the catalog, by design) |
| manual_curation | human — an explicit teach ("this is real") | **0.875 measured** (teach-protocol ceiling: simulated teacher, proves the plumbing; real-user telemetry refines it) |
| keeper_retention | human — silence (kept, not rejected) | **0.5 kept deliberately** atop a measured 0.857 plumbing ceiling — real silence may be inattention, which no protocol can simulate |

**derived_value** — claim per formula identity on a column: *does the data
hold this formula?* The column score is the worse of (best graded formula's
mismatch rate) and (the name-vs-data identity conflict) — a column whose
values perfectly follow a formula its *name* contradicts is entropy, not
cleanliness.

| Witness | Reads | r |
|---|---|---|
| formula_discovery | data — every row, graded against the formula | **0.750 measured** (finding: ~20% partial divergence passes its match-rate grading) |
| llm_hypothesis | LLM — what formula the column NAME advertises | **0.357 measured** (the name-reader fails exactly where names lie — that is its job description, and why pooling weights exist) |

**Scalars** (one grounded statistic, no pool): `type_fidelity` (quarantine
rate), `null_ratio`, `relationship_entropy` (orphan rate),
`cross_table_consistency` (violation rates; failed critical = 1.0),
`dimensional_entropy` (normalized mutual information), `dimension_coverage`
(mean null rate over dimension columns), `temporal_entropy` (broken time
roles), `business_meaning` (1 − LLM naming confidence), `join_path_determinism`
(ambiguous-join count), `benford` (KL surprise — forensic context only,
excluded from readiness by design). `business_meaning` and `unit_entropy` are
candidates to become pools if an independent second witness is built; until
then they are honest single signals.

## The LLM surface — which calls, which model

All semantic features run on **claude-sonnet-4-6** (the "balanced" tier in
`dataraum-config/llm/config.yaml`); the only fast-tier (claude-haiku-4-5) use
is SQL repair. The distinct LLM roles:

| Call | Prompt | What it produces | Consumed as |
|---|---|---|---|
| per-column annotation | `column_annotation` | business meaning + confidence, temporal claim, formula hypothesis, unit | three witnesses (`llm_claim`, `llm_hypothesis`, naming confidence) — one call, several independent fields |
| per-table synthesis | `semantic_per_table` | entity/fact/dimension classification + **relationship confirmation** | the catalog cut (which pairs exist at all) + `llm_judgment` |
| validation authoring | `validation_sql` / `validation_induction` | SQL for the vertical's checks (e.g. TB↔GL reconciliation) | `cross_table_consistency` executes it deterministically — the LLM authors, the data decides |
| slicing analysis | `slicing_analysis` | slice dimensions + time axes | the substrate `structural_reconciliation` computes over |
| lineage proposals | `business_cycles` | events→measure aggregation candidates | disposed deterministically by reconciliation arithmetic |

The division of labor is constant everywhere: **the LLM picks what to test or
claims what a name means; data grounds it; reliabilities weight it.** When an
LLM is systematically wrong, the fix is its instructions or its evidence (two
shipped this week: the due-date validation hint, the relationship selector's
evidence hierarchy) — never a patch on its answer.

## The teachings

A teach is a human answer that becomes config (an overlay), re-enters the
pipeline, and closes the conflict it answers. Current teach types:

| Teach | Answers | Closure status |
|---|---|---|
| `null_value` | "this token IS a null / IS a value" | **proven** (unit + e2e: C collapses) |
| `concept_property` | "this concept's temporal behavior is X" | **proven** (e2e: C 0.305 → 0.007) |
| `unit` | "this column is in kEUR" | **proven** (built + e2e) |
| `validation` (expected_formula) | "this column's expected formula IS X" | **proven** e2e (DAT-447: derived_value `inspection_total` 0.833 → 0.000 post-teach; declared claim anchors the score, naming dispute stays in evidence) |
| relationship `confirm` / `keep` / `reject` | "this relationship is real / keep it / wrong" | **proven** (DAT-447: `confirm`→manual / `keep`→keeper enter beside the llm row; the human witness materializes and is measured — the confirm-never-materializes gap is closed) |
| `rebind` | "this column belongs to concept Y" | applier built; **CUT at the kill gate for now** — the corpus has rebind suggestions but no separation margin (pure-measurement ΔU ≈ 0.08, inside LLM noise); needs a corpus with an unbound/ambiguous concept |
| `expected_dependency` | "these columns are dependent by design" | applied (read by `dimensional_entropy`) |
| `concept` / `type_pattern` / `cycle` / `metric` | bind a concept / parse pattern / cycle / metric | appliers registered; **closure unproven** — no honest scenario yet (concept needs a U-drop surface; type_pattern a quarantine-pattern corpus; cycle/metric an entropy/readiness surface that reads the vocabulary back). These are the harness's skip rows — its honest coverage map. |

## State of the union

**The outcome that matters first**: across every labelled run to date (clean at
4 seeds + the injected detection-v1 + three calibration corpora), the
deliverable scoreboard shows **zero silently-wrong numbers delivered**. On the
injected leg, 6 of 7 out-of-tolerance metrics were prevented (warned via
non-ready bands on their lineage columns) and the attribution machinery traces
every one to the TB↔GL watcher. Clean legs: no false warnings at the metric
level, on any seed.

**Measurement status** (the full per-detector grid lives in
`calibration/detector_coverage.yaml`):

- Proven through the live pipeline, with measured reliabilities:
  `null_semantics`, `temporal_behavior`, `derived_value`,
  `cross_table_consistency` (scalar), plus recall/precision baselines for the
  simple scalars.
- Working but on baseline evidence: `relationship_entropy`, `unit_entropy`,
  `business_meaning`, `temporal_entropy`, `type_fidelity`, `null_ratio`,
  `benford`.
- Verified scoring, no recall fixture possible/built yet:
  `dimension_coverage` (nothing injects into it), `join_path_determinism`
  (needs two semantically distinct FKs to one table — testdata gap),
  `dimensional_entropy` (its current recall pass is vacuous: double-entry data
  is naturally mutually exclusive).

**The real, honest gap — in order of how much I'd worry:**

1. **The relationship chain was the weakest end-to-end path — now fixed and
   proven on the calibration corpus, with one honest remainder.** The corpus
   caught the LLM selector rejecting 7 of 11 genuine FK pairs on normal
   name-suffix variation (`facility_ref` → `facility_id`) despite perfect
   containment, and a one-way lookup bug keeping the value_overlap witness
   silent in live adjudication. Both fixed; the post-fix re-run confirmed
   11/11 genuine pairs (all suffix-mismatched ones recovered), rejected 4/4
   designed spurious, and produced the first in-contract measurements
   (value_overlap and llm_judgment at 0.923, n=11 — widen over seeds). The
   remainder closed same-day: the teach protocol (ground-truth verdicts →
   same-session re-run → rig over the post-teach claim rows) measured the
   human witnesses — the full circuit (the system asks for the verdict, the
   verdict becomes a witness, the witness's reliability gets measured) is
   proven end to end, and relationship_discovery is the fourth and last
   pooled measurement to flip calibrated. What remains is real-user
   telemetry: every protocol number is a deliberate-teacher ceiling, and
   keeper_retention deliberately keeps its 0.5 stance until real silence
   (which may be inattention) is measurable.
2. **Partial formula divergence under ~20% passes formula_discovery's
   grading** (measured: 0% accuracy on the partial stratum). The pooled
   conflict and the scalar still catch it at the column level, but the
   witness's per-claim vote is weak exactly where divergence is subtle.
3. **Teach closure is proven for 5 of the 9 applier-backed teach types**
   (null_value, concept_property, unit, validation/expected_formula,
   relationship), unified into one parametrized harness
   (`calibration/test_teach_cycle.py`) whose remaining rows are honest skips
   with precise reasons — the coverage map, not faked closure. `rebind` is
   kill-gate-CUT for now (no separation margin in the corpus);
   `concept`/`type_pattern`/`cycle`/`metric` need scenarios that don't exist
   yet. All four pooled measurements now route their conflict into an
   executable teach suggestion (the PR #284 routing gap is closed). Two
   harness design notes for later: (a) the derived/relationship corpora now
   carry *persisted* teach overlays, with recall coupled via a teach-answered
   skip — a self-contained teach→assert→teardown design would decouple them
   at the cost of a full re-run per test; (b) workspace-scoped *concept*
   teaches leak cross-session (a concept is not column-scoped), so any future
   concept_property/concept closure run needs a teardown discipline — a
   latent leftover was caught and removed this session.
4. **Run-to-run LLM variance vs captured baselines.** Clean scores now have
   measured bands (replacing point captures), but the readiness baseline is
   still a point capture; one column (`payments.amount`) flips its temporal
   band on roughly 1 seed in 4. Policy decision pending: band the readiness
   baseline the same way.
5. **The outcomes scoreboard only exercises GL-derived deliverables.** A
   second deliverable spec reading invoices/payments would exercise the
   parked cross_table rate-path weight and add genuinely new label data.
6. **Slice-conditional nulls**: statistic gated and proven separable
   (Cramér's V under the Cochran rule), not yet implemented as a family +
   detector.
7. Single-witness candidates (`business_meaning`, `unit_entropy`) stay
   un-pooled until an independent second witness passes the entry criterion —
   acceptable, but they cap how much disagreement we can surface on naming
   and units.

**What "iterating on this" looks like** (the loops are all one command): add a
family member → edit a strategy YAML; re-measure witness trust → run the rig,
apply by hand with provenance; re-measure clean behavior → resweep + rebuild
bands; every batch re-labels the scoreboard and attributes each prevention to
the detector that earned it.
