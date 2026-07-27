# RFC 5 — Evaluation: calibration, functional tests, and comparability

*Status: golden (new — the drafts had no evaluation part) · Part 5 of 6*
*Depends on RFC 0–4. The law it must not contradict: [`../../entropy_eval_architecture.md`](../../entropy_eval_architecture.md)*

---

## Why this part exists

RFC 0–4 describe a product that computes money per entity and compares it to an
expectation. Every claim in them — *this deviation is real*, *this dimension is lit*,
*this scenario is reproducible* — is an assertion about a number. None of those assertions
is currently gradeable end to end, and the drafts contain no evaluation plan at all.

This part states what evaluation has to do for the dimension roadmap, what already exists,
and the four extensions that make results comparable across runs, datasets and verticals.

## The two jobs the test data must do

They pull in different directions and one generator has to serve both.

| | **Detector calibration** | **Functional system test** |
| :---- | :---- | :---- |
| Question | does the measurement separate a known defect from natural variation? | does the product compute the right number and say the right thing about it? |
| Data | clean corpus + **injected pathologies**, severity-laddered | clean, **business-shaped**, fully-known operating data |
| Truth | `entropy_map.yaml` — what was injected where | `ground_truth.yaml` + `metadata_truth.yaml` — the true values and the true model |
| Assertion | **ordering**: injected > clean + margin, monotone in severity — never a point threshold | **value within a declared tolerance**, plus the right abstention when it cannot know |
| Status | mature — 27 graded oracle modules, measured clean bands, teach-closure | **the hole**: the eval grades its *own* golden SQL, not the engine's (DAT-687) |

Both are needed and they are not substitutes. Calibration proves the warning fires;
functional testing proves the number is right. Today we can say "the system would have
warned" (the outcomes scoreboard: right / wrong_prevented / **wrong_delivered**) and we
cannot say "the system computed it correctly", because the golden SQL is ours.

**Consequence for the generator work in RFC 3 lane A1.** The customer/product/revenue
extension is not only a new injection surface. It must emit, for the same rows, the *true*
DB1 per customer and per product group — so the functional test has an answer key. Design
the truth export with the entities, not after.

### A third job, already running: model-capability evaluation

`tfm/` is neither of the two above and should not be folded into them. It grades **models**
(forecasters, density scorers, imputers, conditioners) against a known DGP, in an isolated
environment, with named metrics and pre-registered fail-once gates — the discipline that
CUT scenario row generation in 3.8 seconds and that produced the licence-vs-calibration
finding deciding which engine can ship. Keep it separate, keep it rerunnable, and treat its
probes as the standing gate for anything predictive: a read-out at a new horizon re-runs
the conformal probe, a new lever type re-runs the support-boundary legs.

Its corpus is the same generator's output, which is the point — the same answer key serves
detector calibration, functional tests and model evaluation.

## The measurement that the whole roadmap hangs on

`pipeline error + model error ≤ decision tolerance` is the product's grading contract.

- **model error** — the forecast band. Decided: CQR over a growing calibration set
  (DAT-750).
- **pipeline error** — the error the model *recovery* introduces before any prediction:
  wrong grounding, wrong sign convention, a stock summed across periods, an orphaned join.
  **Unmeasured.** DAT-687 produces it.

Until it exists, three things in RFC 0–2 are claims rather than properties: deviation
significance, "lit" on the coverage map, and any tolerance a scenario inherits. This is the
single highest-value eval item in the roadmap and it is one ticket.

Its unit needs deciding (RFC 1 open question): relative error per graded metric is the
obvious default, reported per dimension and per grounding class, so a band can be attributed
to *what kind of recovery* was uncertain rather than to the pipeline as a lump.

## Comparability: what exists, and the four extensions

Comparability is not a new framework. Three of the four pieces are built or in flight
under DAT-860–863.

**What exists today.**

- **The execution cube** (`calibration/cube.py`): every Tier-3 oracle declares
  `vertical`, the `datasets` it binds to, the deepest pipeline `from_stage` it consumes,
  and an oracle `version`. The declaration is enforced — an undeclared oracle fails the
  suite, so new oracles are born comparable.
- **The immutable verdict store** (`calibration/results_store.py` →
  `calibration/results/verdicts.jsonl`, append-only, git-tracked): one line per oracle per
  pass, carrying dataset, vertical, from_stage, oracle version, status (**including skips**
  — a skip is first-class evidence), and the exact provenance (eval commit, **engine
  submodule commit**, run id). "Did this regress?" is a diff between two passes, not a
  human's memory.
- **Coverage accounting** (`oracle_coverage.json`): graded vs skipped with reasons, per
  strategy — the guard against a run going green because nothing was checked.

**Where it stands right now:** 1,699 verdicts across 9 passes — **all `vertical: finance`,
all synthetic, zero wild rows.** The axis exists; only one value has ever been on it.

**The four extensions.**

1. **Verdicts carry values, not only statuses.** A pass/fail tells you a threshold held; it
   cannot tell you the margin shrank by half. For every oracle with a numeric core — recall
   margins, band scores, metric deviation vs tolerance, binding precision/recall — record
   the measured value and the threshold that judged it. This is what turns the store from a
   regression alarm into a trend instrument, and it is the prerequisite for reporting a
   pipeline-error *distribution* rather than a pass rate.
2. **Wild runs write to the same store.** The wild lane grades a scoreboard and prints it;
   nothing is retained. Same schema, same coordinates, `tier: wild` — with the standing rule
   unchanged: **wild results are findings, never build gates**, because wild data has no
   recall truth. Retaining them is what makes "has our false-positive rate on unseen schemas
   moved?" a query.
3. **`dimension` becomes a coordinate.** Once concepts and metrics carry the facet
   (RFC 3, B2), oracles that grade a dimension's flagship metric declare it. The
   coverage map's gate then reads directly off the store: a dimension is *lit* iff a
   dimension-tagged oracle graded its metric within tolerance on the last pass.
4. **Non-determinism is reported, not suppressed.** Known live: ~25% of 1:1 FK orientations
   flip between runs; the readiness baseline is a point capture while clean scores have
   measured bands. The discipline is epochs plus a named reducer, with reducer variance
   reported as a statistic — never an override of a judge, never a relaxed oracle. With
   values in the store this becomes computable from passes that already happen.

Together these four answer the question directly: **comparable across runs** = the verdict
store keyed on (eval commit, engine commit, run id); **across datasets** = the cube's
dataset axis with per-dataset baselines; **across verticals** = the cube's vertical axis,
which today has exactly one value and needs a second (the wild lane is the cheapest one).

## The gates the dimension roadmap needs

Each is small and each prevents a specific, likely failure.

| Gate | Fails when | Protects |
| :---- | :---- | :---- |
| **Coverage-map honesty** | a dimension reads *lit* with no graded metric behind it | the map becoming the lie it exists to prevent |
| **Binding precision per dimension** | new concepts push binding precision/recall below the bar on a corpus with truth | the DAT-709 failure mode multiplying with the prior surface |
| **Prior non-suppression** | a prior outranks recovered structure that the evidence supports better | RFC 0's differentiator, currently an intention with no test |
| **Target selection and abstention** | the operator picks a stale plan over a naive target, or reports −100% for an entity with no history | the fastest way to lose trust in week one |
| **Person-grain refusal** | a person-grained column is bound instead of quarantined | Throughput's compliance claim |
| **Allocation reproducibility** | the same figure under the same named scheme and model version does not recompute identically | every what-if claim downstream |

These are oracles in the existing grammar — set statistics, ordering, exact-match verdicts,
xfail(strict=False) where an LLM judgment is in the loop. No new assertion machinery.

## What must not change

- **The tier discipline.** Millisecond Tier 1/2 first; Tier 3 is a budgeted gate with a
  named hypothesis, never a dev loop. The dimension work adds oracles, not pipeline runs.
- **Recall is ordering, never a tuned threshold.**
- **Wild is a scoreboard, never a build gate**, and never a correctness certificate.
- **The kill gate.** A new measurement gets a named statistic and a millisecond separation
  probe before anyone builds it; CUT is the default outcome. This applies to everything RFC
  1 proposes — a peer-comparison estimator, a plan-freshness grade and a deviation-
  significance rule are each a measurement, and each owes a probe before a sprint.
- **No deterministic overrides of LLM judgments**, ours or the engine's. Entropy is
  disagreement; patching a judge to make a test pass is Goodhart at the harness level.
- **One assertion grammar.** Freeze it; extend the plumbing (which is exactly what
  DAT-860–863 are doing). A second harness is a second thing to maintain, not a second
  signal.

## Sequencing of the eval work

It rides along; it does not wait.

| With RFC 3 step | Eval work |
| :---- | :---- |
| **A1** generator | truth export designed with the entities — DB1 per customer and per product group; new injection families for customer/product/order defects; the lever pairs as what-if ground truth |
| **A2** priors | dry-run coverage read over the new corpus and one wild corpus |
| **A3** | **DAT-687 pipeline-error term** — the item everything else's honesty depends on |
| **A4** | values in the verdict store; wild runs into the store; `dimension` as a cube coordinate; reducer-variance reporting |
| **B1** ladder | per-axis additivity oracles; the graded unit-metric exit criterion |
| **B2** facet + map | coverage-map honesty gate (no *lit* without a graded metric) |
| **B3** frame priors | **binding precision/recall per facet must not degrade**; no-leakage check (a non-finance dataset frames with no finance vocabulary); prior non-suppression oracle |
| **B4** operator | target selection + abstention oracle; entity birth/death cases |
| **B5** allocation | allocation reproducibility oracle; two-scheme divergence as a *reported* statistic, not a failure |
| **B6** Capital, forecast, what-if | conformed-dimension oracle for Demand × Capital; backtest scoreboard; interval coverage as a measured statistic (does the 80% band cover 80%?); in-support vs out-of-support what-if grading against the lever counterfactual |
| **B7** | person-grain refusal oracle before Throughput ships |
