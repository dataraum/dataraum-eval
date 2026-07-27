# RFC 1 — The target operator, forecast, and what-if

*Status: golden (grounded against the code 2026-07-27) · Part 1 of 6*
*Depends on RFC 0. Per-dimension levers in RFC 2. Build order in RFC 3. Grading in RFC 5.*

---

## Motivation

RFC 0 specifies a deviation engine: `entity × metric-per-unit × comparison`. The
comparison term does not exist in the engine — not thinly, at all. `forecast`,
`what-if`, `scenario`, `plan-vs-actual` return zero hits across the engine source. Among
the 26 element views of the operating-model property graph there is no target, no plan,
no interval. The only `tolerance` in the system is a validation-check parameter
(`deviation <= tolerance` on a data-integrity check), which is a different thing.

So this part builds a missing third of the grammar, in an order that puts the cheap,
differentiating half first.

## Part 1 — The target operator

### The unification

Prior period and internal peer are not alternatives to a forecast. They *are* forecasts
with the model left implicit:

| Target source | Underlying model | Interval | Cost to build |
| :---- | :---- | :---- | :---- |
| **Plan** | human-supplied prediction | none stated | a new source kind + grain binding — the expensive one |
| **Forecast** | learned model over history and drivers | explicit, conformal (measured — see below) | a new runtime (DAT-749/750); the engine choice is settled by licence, not by accuracy |
| **Prior period** | naive persistence (`ŷ = y₍t−1₎`) | derivable from history variance | SQL over the metric graph + `og_temporal_coverage` |
| **Internal peer** | cross-sectional central tendency | derivable from sibling spread | SQL over the metric graph + the slice catalog |
| **Standard / ceiling** | definitional (routing time, theoretical capacity) | none — it is a definition | declaration only; typed separately, never confused with plan |

Making this explicit turns the fallback chain from five unrelated behaviours into **one
mechanism with five estimators**, each carrying the same three properties: a stated
model, an uncertainty interval, and an evidence grade.

### Build the operator before the estimators that are expensive

The differentiating line is not the forecast. It is:

> The system surfaces a deviation only when it exceeds the target's own uncertainty, and
> it states which target it used and why the others were not.

That line is delivered by the **operator** — the resolution order, the disclosure, the
interval, the honesty register applied to the comparison rather than to the data. Two of
the five estimators (prior period, internal peer) are pure SQL over substrate that
already exists. The forecast needs a torch worker, a calibration set, and a backtest
harness.

**So: ship the operator with prior-period + internal-peer + definitional standard first.
Forecast plugs into the same slot as a third estimator. Plan ingestion is a separate,
larger piece of work.** This inverts the original draft's order, and it follows from the
draft's own unification argument: if forecast is one estimator among five, then the
five-slot mechanism is the deliverable, not the hardest slot.

**Decided 2026-07-27 (Philipp: "yes, forecast is out"): forecast is out of the near-term
roadmap entirely.** DAT-750/751 are parked until a customer asks for projected targets;
the operator's forecast slot stays designed and stays empty. A grounding correction makes
the parking free: the engine contains **no forecast code at all** — no runtime seam, no
torch dependency, no hit in git history. What DAT-750 "resolved" is the calibration
*decision* (CQR over a growing calibration set), not a build; nothing is sunk. `tfm/`
remains the standing reference and re-gate harness. Decision recorded on DAT-749.

### Evidence-ranked resolution

Order of preference, availability-gated:

1. **Plan**, if current and at matching granularity. A stale or wrong-grain plan is a
   worse target than a naive one and is demoted, not preferred. Plan freshness is typed
   evidence like any other.
2. **Forecast**, when the history gate clears.
3. **Prior period**, as the persistence fallback.
4. **Internal peer**, offered *alongside* rather than instead of the above.

Where a definitional standard exists (Capacity ceilings, Throughput routing times), it is
shown as a separate typed target rather than competing in this order.

### The interval has two error terms, and we have measured neither

This is the correction that governs the whole RFC.

The product's grading contract is `pipeline error + model error ≤ decision tolerance`.

- **Model error** — the forecast's own uncertainty. Decided and gated: **CQR (conformalized
  quantile regression) over a monthly-growing calibration set**, resolved 2026-07-14 under
  DAT-750; adaptive conformal (ACI) was probed and rejected (the under-coverage root cause
  was a *frozen* calibration set, not the α policy). Re-gate trigger recorded: any read-out
  at horizon ≥ 3, or slower-than-monthly feedback, re-runs that probe.
- **Pipeline error** — the error the *model recovery* introduces before any forecasting
  happens: a concept grounded to the wrong extract, a sign convention applied to one side
  of a comparison, a stock summed across periods, an orphaned join silently dropping rows.
  **This has never been measured.** The eval's deliverable scoreboard grades
  *eval-authored golden SQL* against generator truth — deliberately not the engine's own
  SQL — so it proves the warning bands work, not that the number is right. **DAT-687**
  ("grade the product answer path") is the ticket that produces the term.

A band that covers only the model error is a band that lies by exactly the amount the
recovery is wrong. Therefore:

> **Gate: no deviation-significance claim ships before DAT-687 reports a pipeline-error
> distribution on at least one graded unit metric.**

This is not a delay for its own sake. The measurement is also the sales asset — a stated,
measured recovery error is something no competitor publishes. And it gates the *claim*,
not the build: the forecast and what-if work below proceeds in parallel; what waits is the
sentence "this deviation is significant".

## What the TFM track already measured

`tfm/` (DAT-741 / 743 / 744) is a measured capability evaluation on the known-DGP corpus,
not a survey. It answers most of what the original draft left open, and two of its results
change the design rather than confirming it. Raw rows in `tfm/output/phase1/*.jsonl`;
findings in `PHASE0/1/2_FINDINGS.md`.

**Forecast quality and calibration (P1, 135 series × 48 months, rolling origins).**
TabPFN-TS-3 is the best distributional forecaster (best CRPS) *and* essentially calibrated
out of the box — 0.816 empirical at nominal 80%, 0.965 at 95% — so it needs no conformal
wrapper. LightGBM matches its point accuracy and is badly overconfident (0.651 at nominal
80%). TabICL's forecaster lands at ETS level and **is** improved by CQR (+2 pp at both
levels, ≤5% width cost), though a static calibration under-corrects across temporal drift.

**The licence fact that decides the engine choice.** TabPFN-3 weights are
**non-commercial**; TabICL is BSD-3 with ungated weights, ships fine-tuning, its prior
generator and its training code. So the calibrated winner cannot go in the product and the
open engine needs the conformal wrapper — which is exactly why DAT-750's gate resolved to
*CQR over a growing calibration set*, and why TabPFN-TS remains valuable as the **eval
reference** rather than the runtime.

**No forecaster tracks a regime change (P5 Leg A).** Recovered effect fraction after a
structural break, pooled: TabICL ≈ 0.61 / 0.34 / 0.69 at 1, 2 and 6 months of post-break
context; ETS ≈ 0.41–0.54; TabPFN-TS the *most* conservative at 0.27–0.40 (its seasonal
anchoring holds it to the old regime); seasonal naive ≈ 0. **Even six months in, none of
them fully tracks it.** That is the measured reason what-if must run through explicit lever
conditioning and never through the forecast read-out alone — a rule with a number behind
it, not a preference.

**In-support what-if passes decisively; out-of-support honesty differs by engine (P5 Leg
B).** With the lever as an explicit feature, TabICL recovers a held-out interpolated effect
at **1.011** with WAPE 0.006 and 0.948 coverage; LightGBM manages 0.563 at 0.375 coverage —
trees do not interpolate a continuous lever from seven observed values. Out of support,
TabICL under-extrapolates (0.63–0.66 of the true effect) **and says so** — intervals widen
17–24× and coverage holds. TabPFN-3 out of support was *confidently wrong*: on the downside
query its 80% interval covered **0.0%** of true values with bands 8× narrower. This is the
whole argument for the support-boundary guard, and it says the guard must be engine-specific:
TabICL's own widening is a trustworthy signal, TabPFN's is not.

**Scenario row generation is cut.** `TabICLUnsupervised.generate()` produced
value-plausible, structurally lawless rows — debit/credit mutual exclusivity 0% (real rows:
100%), the ledger identity `net = debit − credit` holding on 9.3% (real: 100%). Killed at
the pre-registered fidelity gate in 3.8 seconds. Scenarios are computed through the metric
DAG, never by generating rows.

**We can already grade what-if.** The generator carries `Lever(period_k, factor,
type="price_level")` as a **DGP intervention**: amounts scale from month *k* and propagate
through the cascade (AR → receipts → cash → TB/BS), and because scaling happens after every
RNG draw with no control flow branching on values, a same-seed pair is an **exact
counterfactual** — proven by a test, recorded in `intervention.yaml` beside the data. That
is ground truth for a what-if read-out, and it exists today. It is also the template for
every further lever: a lever is a DGP parameter, not a post-hoc injection.

*Grounding caveat (2026-07-27 testdata read): narrower than it reads.* One lever type
(`price_level`), Python-API only (no CLI), and the revenue amount it scales has no
`units × price` decomposition — the exactness rests on scale-after-every-draw with no
downstream control flow branching on the value. A volume lever on a real operating chain
changes event *counts* and would diverge a sequential RNG stream. The A1 generator build
therefore carries a named design constraint: **key RNG streams by stable entity ids, not
draw order**, so same-seed counterfactuals survive the operating-model rebuild (DAT-884;
the string-keyed-RNG precedent exists in `entropy/injectors.py`).

Two consequences worth stating plainly. The predictive half is **further along than the
grammar half** — we have measured, calibrated forecasting and a passed in-support what-if
gate, and we do not yet have a predicate on an extract. And the honest-uncertainty
behaviour that RFC 0 calls the product's register is *measured*, not aspirational: the
engine we can ship widens where evidence ends.

### Entity birth and death

A forecast, a prior-period comparison and a peer set all assume the entity existed before
and has comparable siblings. Assortment churn, supplier onboarding, new lines and new
segments break all three. The model must distinguish *deviation* from *absence of history*
and say so, rather than reporting a phantom −100%.

This is a correctness requirement, not an edge case; it is the most common way predictive
features lose trust in the first week. The raw material exists — `og_temporal_coverage`
carries per-entity time extent — and nothing consumes it for this. It ships **with** the
operator, in the same slice, not after it.

## Part 2 — What-if as the inverse operator

Forward: `entity × metric-per-unit × target → deviation`

Inverse, two modes:

- **Projection** — perturb a lever, propagate through the recovered model, re-derive the
  metric.
- **Goal-seek** — fix the metric, solve for the lever.

Same machinery, opposite directions. The decided shape (DAT-752), now with the measurement
behind it: what-if is **explicit lever conditioning, never the forecaster run alone**
(P5 Leg A — no forecaster tracks a regime change even six months in), with a mandatory
support-boundary guard (P5 Leg B — in-support recovery 1.011, out-of-support 0.63–0.66 with
17–24× interval widening on the engine we can ship, and 0% coverage on the one we cannot).

### Allocation is the substrate, not the provenance story

**An explicit allocation rule is what makes propagation computable.** A simulation can
only push a change from a lever through to cost-per-customer if the path from cost to
customer is a declared, inspectable rule rather than a hidden aggregation. Every argument
for making allocation explicit (RFC 0) is doubled here, and the decision for named, plural
schemes is a hard requirement: a scenario computed under an unnamed scheme is not
reproducible.

Since allocation does not exist in the engine at all, **allocation is a hard predecessor
of what-if**, and what-if is therefore late in RFC 3 — after targets are trusted and at
least one allocation scheme is shipped and disclosed.

### Typed levers

Levers are not free-text. A closed set keeps simulation auditable and the UI finite.

| Lever type | Perturbs | Example | Dimensions |
| :---- | :---- | :---- | :---- |
| **Volume** | quantity on an entity | +10% units on product group C | Demand, Offer, Supply |
| **Price** | unit value | −2% list price on segment B | Offer, Supply |
| **Mix** | share across siblings | shift 15% of volume from channel A to B | Demand, Offer, Supply |
| **Rate** | a ratio in the model | scrap rate on line 2 from 4% to 2.5% | Throughput, Supply, Capacity |
| **Timing** | a duration | supplier lead time −3 days; DSO −8 days | Supply, Capital, Throughput |
| **Capacity** | an availability ceiling | one additional shift on line 2 | Capacity |
| **Allocation key** | the rule itself | freight by weight vs. by revenue | all |

The last one is distinctive. No other tool lets a CXO ask *"is this customer unprofitable,
or is my allocation rule wrong?"* and get a computed answer.

### Hard rules

- **No path, no simulation.** A lever may only be perturbed against a metric if the
  recovered model contains a structural path between them. This is directly expressible:
  refuse when no path exists in the operating-model graph between the lever's concept and
  the metric's groundings. Where none exists the scenario is refused, with the missing link
  named — and the refusal is itself a coverage-map entry.
- **Outside support, no projection.** The DAT-752 support-boundary guard, stated as a
  product rule rather than an implementation detail.
- **Scenarios are pinned artifacts.** Every scenario stores the model version, the
  allocation scheme, the target source and the lever set. A scenario that cannot be
  recomputed identically does not exist.
- **Projection is not prophecy.** Simulated results inherit and compound the intervals of
  their inputs — including the pipeline-error term. A projection is displayed with its band
  or not at all.
- **The company model outranks the prior here too.** Elasticities and propagation
  coefficients are recovered from the company's own history where evidence supports it.

## Part 3 — Coverage map extension

Two states join lit / partial / dark, per dimension:

- **Forecastable** — enough clean history at this granularity to fit and validate a model.
  Gated on history, not on connection.
- **Simulatable** — the structural paths and allocation rules needed to propagate a lever
  are present.

Each state names its own next step and its own commercial line:

- partial → "connect planning data and the Soll column lights up"
- not yet forecastable → "eighteen more months of history, or connect the archive, and
  this metric gets a projected target"
- not yet simulatable → "the link between goods receipt and order line is missing; supply
  it and this dimension becomes a scenario surface"

## Where the existing lane already answers this

DAT-749 is the epic of record for the predictive half. Its forecast children — DAT-750
(runtime seam + conformal wrapper; the CQR gate is a resolved *decision*, no code exists)
and DAT-751 (metric forecast read-out) — are **parked as of 2026-07-27** (Part 1 above).
The what-if tail stands unchanged: DAT-752 what-if lever conditioning, DAT-753 scenario
generation via Monte Carlo through the metric DAG, DAT-754 flagged gap imputation (never
silent, provenance-marked), DAT-755 the driver-SHAP kill gate, DAT-765 the Sarawagi
surprise eval family.

Its evidence base is `tfm/` — an isolated uv project with its own environment, so the
torch stack never touches the calibration env. Treat it as the reference implementation
and the standing gate: every claim above has a rerunnable probe behind it, and DAT-755
(driver-SHAP) plus DAT-765 (Sarawagi surprise) are the two gates still open.

This RFC does not re-plan that lane. It adds three things to it: **the operator that owns
the slot** (Part 1), **the pipeline-error term the bands must include**, and **the
sequencing rule that the cheap estimators come first.** And it takes one thing from it: the
predictive half is measured and ready before the grammar half is, which means forecast and
what-if are **not the long pole** — they are waiting on a metric worth forecasting.

## Open questions

Pruned to what is actually open — the calibration method, the what-if shape, and the
imputation policy are decided under DAT-749 and are not re-opened here.

- **The pipeline-error measurement itself.** What is the unit — relative error per graded
  metric, per dimension, per grounding class? Whatever DAT-687 chooses becomes the
  vocabulary of every band we display.
- **Plan freshness typing.** What evidence establishes that a connected plan is current
  enough to outrank a forecast? Needs a real plan artifact to answer; parked until one
  exists.
- **Plan grain binding.** Plans arrive aggregate; data is transactional. Binding a
  plan row to a recovered grain is a new binding problem, not a file import. Scope it
  before promising plan ingestion.
- **Backtesting display.** Do we show the forecast's own track record? Argued yes — a
  target that publishes its hit rate is unusual enough to be a differentiator, and the
  harness is a listed work item.
- **Interval presentation.** A band is correct and most executives read it as hedging.
  What is the plain-language form? ("Between X and Y in four of five comparable periods.")
- **Scenario composition.** Do two scenarios compose, and how are interacting levers
  reconciled? Probably: composition allowed, interaction terms flagged as unmodelled.
- **Ownership.** Is a scenario a workspace artifact or a personal sketch? Likely both,
  with an explicit promotion step.
