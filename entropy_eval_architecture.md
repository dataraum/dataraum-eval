# Entropy Eval — Architecture & Method

> **Status:** reset (2026-06-08). This supersedes the implicit "run the calibration
> suite until it's green" workflow. It is the definition of what eval *is* and how
> we develop entropy measurements.

## Why this document exists

We spent days tuning entropy measurements by **booting Postgres + Temporal + an LLM
pipeline (~10 min) to test pure math**, then guessing at the next tweak from slow,
noisy feedback. The result was a hack-and-compile loop — "shitty reality → shitty
reality" — with no convergence. Two root causes:

1. **The test pyramid was inverted.** A drift / conflict / surprise score is a *pure
   function*. It must be tested in **milliseconds** on synthetic + recorded data, not
   by re-running the whole framework.
2. **Eval drifted from purpose to proxy.** We optimized "does the injection score
   > 0.3 on one fixed dataset" instead of "is this measurement *right*, and does it
   tell a practitioner something *true and actionable*." That is Goodhart at the
   harness level.

This document fixes both.

## What eval proves

A measurement earns its place **only if all three hold**, and eval's job is to prove
each — fast:

| Property | Meaning | Proven by |
|---|---|---|
| **Right** | a grounded statistic, not an improvised boost curve | Tier 1 unit (synthetic) |
| **Useful** | tells the practitioner something *true and actionable* — enables a fix or teach, or is genuine **context** for a query / aggregation / report decision. If it tells nothing actionable, **cut it.** | the measurement contract (below) |
| **Stable** | a teach *closes* it (conflict/ignorance or score drops), provably | Tier 1 unit (teach-closure) |

"Scores an injection" is **not** a goal. It was the proxy we Goodharted. Recall is
asserted as **ordering / calibration** (injected > clean + margin; monotonic in
severity), never a point threshold.

## The test architecture — invert the pyramid

| Tier | Speed | Docker? | Proves | Where iteration happens |
|---|---|---|---|---|
| **1 — unit** | ms | no | the statistic as a pure fn over **synthetic** fixtures: clean < injected ordering, calibration shape, edge cases, **and teach-closure** | **ALL measure + teach design** |
| **2 — recorded** | sec | no | the statistic over **frozen real pipeline outputs** (the SQLite fixture below) — real data shapes, no pipeline | confirming the measure survives reality |
| **3 — integration** | min | yes | the **assembled** framework end-to-end (generate → pipeline → measure → readiness → teach) | wiring only; **milestone gate, NOT the dev loop** |

**Rule:** every measure and teach is designed and debugged in Tier 1/2. The live
suite (Tier 3) runs **once per milestone**, never per tweak.

> Worked example of the cost: "does KS separate a 1.35× shift from natural monthly
> volatility?" is a **2 ms Tier-1 test** on two synthetic samples. We answered it with
> 10-minute pipeline runs. Never again.

### The recorded fixture (Tier 2)

One live run produces real intermediate data; we **extract what the measures consume**
into a portable **SQLite** file committed to the repo (`calibration/fixtures/…`). It
holds, for both a **clean** and an **injected** session:

- raw per-period numeric **values** (for drift / KS) — from the DuckDB slice tables
- **quarantine tokens** + counts (for null_semantics) — from the DuckDB quarantine tables
- leading-digit **distributions** / numeric samples (for benford)
- per-slice **statistical profiles** (for dimensional_entropy) — from Postgres
- **witness distributions** (for pooling C/U) — from `claim_witnesses`
- **semantic annotations** (units, roles, null_tokens)

After capture, **no measure or teach is ever debugged through the live pipeline again.**
Refresh the fixture only when the pipeline's *output shape* changes (a schema/phase
change), via `scripts/capture_fixture.py`.

## The measurement contract

Written **before code**, one entry per measurement (see catalog below):

- **Purpose** — what does it tell the practitioner; what decision / context does it serve?
- **Earns its place?** — yes / conditional / cut. If it enables no fix/teach and is no real context, it is cut.
- **Statistic** — the grounded method.
- **Fix / teach** — the action that closes it.
- **Unit proof** (Tier 1) — synthetic ordering + calibration + teach-closure.
- **Recorded proof** (Tier 2) — assertion against the SQLite fixture.
- **Integration case** (Tier 3) — the one end-to-end scenario.

**Measurement surfaces are part of the contract.** A witness's reliability is
measured ONLY on the population it votes on in production — never on a wider
artifact that happens to be persisted and labelled. The standing instance:
**relationship entropy exists only on the defined catalog (post-LLM
confirmation)**. Candidate rows are a generous structural list — pre-contract
hypotheses, useless and dangerous as an entropy or calibration surface (the
DAT-405 lesson; relearned 2026-06-11 when a value_overlap r synthesized from
candidate rows of LLM-rejected pairs was shipped and withdrawn). Pairs that
never reach the catalog are a finding about the SELECTOR (coverage), not votes.

### Agent-metadata oracles (DAT-680 P1)

Detectors are graded against `entropy_map.yaml`; the **agent layer** — the
relationships, labels, cycles, validation SQL, metric-graph SQL, drivers, and
additivity verdicts the engine persists in `current_*` views — needs the same
discipline. Its ground truth lives in `calibration/fixtures/metadata_truth.yaml`
(hand-authored today; generator-exported under DAT-682), and the assertion reuses
the existing grammar: a named set-statistic (precision/recall/F1/Jaccard) for
set-valued claims, exact-match verdict accuracy for categorical ones — never a new
framework.

The **determinism split** governs that grammar. A claim fixed by structure alone
(a `COUNT(DISTINCT)` never reconciles under SUM) is **hard-asserted** — a mismatch
is a real defect and no upstream label can game it. A claim that depends on an
upstream detector label or grain (is this column a stock? is this fact an event? —
stock/flow is the pooled `temporal_behavior` detector, not a raw LLM call) is a
**diagnostic** (xfail, strict=False): hard-grading it here would re-grade that
upstream detector deterministically through a downstream oracle — Goodhart at the
harness level — so it is graded in its own labeling lane.

**First entry — metric additivity (DAT-716/718).** `current_metric_additivity`'s
per-`(target_kind, target_key)` verdict (does a categorical / time breakdown
reconcile to the unsliced total?) vs the derived truth = function-symmetry ×
stock/flow × grain. Hard core: AVG / COUNT(DISTINCT) / ratio → non-additive.
Diagnostics: SUM(flow) additive, SUM(stock) time-stripped, COUNT additive only on
an event fact — a divergence feeds DAT-685 (stock/flow) or DAT-716 (grain).
Tier-1 fixture gate `calibration/unit/test_metadata_truth.py`; Tier-3 oracle
`calibration/test_metric_additivity_e2e.py`.

## Measurement catalog

The grounded statistic per measurement, and the honest "earns its place" call. The
**conditional / cut** rows are where the reset pays off — purpose-first kills or
reframes measurements that only ever produced noise.

| Measurement | Purpose / context it serves | Earns it? | Grounded statistic | Fix / teach |
|---|---|---|---|---|
| **null_semantics** | "is `#ERR` a null?" — don't silently aggregate contested markers | **yes** | pooling **C/U** over witnesses | null_value overlay → witness flips |
| **type_fidelity** | type-cast failures → structural trust | **yes** | raw quarantine **rate** (drop `_boost_rate`) | re-type / teach pattern |
| **null_ratio** | missing fraction → completeness | **yes — KEEP (DAT-540 eval-gate PASSED, 2026-06-22)** P5/ADR-0013 band-impact ablation (`scripts/calibrate_band_impact_ablation.py`, arm A = all loss objects vs arm B = null_ratio ablated; engine `compute_loss_risk` + `LossConfig.band`; corpus `detection-v1`): score separates (inj_max 0.71 vs clean_max 0.53, +0.18), and the injected `cost_center` (0.71) reaches `investigate` on **all three intents ONLY because of null_ratio** (a true band lift from `ready`) — 0 false lifts on clean, 0 redundant. Marginal band value proven: the raw missing fraction moves a band that maps to a real wrong/unsafe answer no other measurement covers on that column. | raw **rate** | fill / document |
| **slice-conditional null (DAT-473)** | nulls concentrated in specific slices — dataset-level null_ratio hides a 60%-null slice behind a 5% overall rate, silently biasing that slice's aggregates | **BUILT** (kill gate passed 2026-06-11; shipped 2026-06-15 — `slice_conditional_null` detector + testdata family + eval recall/teach wiring). **DEMOTED off the loss path (DAT-540 eval-gate, 2026-06-22; engine branch `refactor/dat540-slice-conditional-null-demote-loss`, commit `b11b94d4`, PR pending) → informative DirectSignal, benford/dimensional_entropy lane.** Recall + teach are proven (above), but the P5/ADR-0013 **band** ablation (`scripts/calibrate_band_impact_ablation.py`, arm A vs arm B = `slice_conditional_null` ablated; corpus `detection-slice-null-v1`) falsifies its loss-path value two ways: (1) its only OBSERVABLE band move is a **false positive on benign structural conditionality** — clean `bank_transactions.payment_id` (an optional FK, null-by-design when a transaction is not a payment, as the column's OWN `business_meaning` documents: *"null when the transaction is not linked to a payment"*) scored **V=0.97 on slice `counterparty` → blocked aggregation**; optional FKs are ubiquitous in financial data, so the untaught default is to block them. (2) On its INJECTED columns (`credit`/`debit`) the aggregation band is **already set by `cross_table_consistency` (0.80)** — ablating slice_conditional_null moved **NO** band (0 true lifts), so its marginal loss value is unproven (confounded by a GL-reconciliation flag, not separable on the existing slice corpus). A loss signal whose only visible band move is a false block on a benign-by-default pattern is anti-predictive — the **benford/DEMOTE signature**: keep the Cramér's V score + `expected_dependency`/`documented_dependency` teach as a DirectSignal (context), remove the loss row (`loss.yaml`) so it stops driving bands. The Cramér's V statistic + recall score-separation are UNCHANGED. Caveat (in the ticket): this row's slice substrate is itself under P1 review; a clean (un-confounded) corpus could later re-test for a genuine KEEP, but the over-fire stands regardless. | bias-corrected **Cramér's V** (Bergsma) on the 2×K is-null × slice table under the **Cochran validity rule** (any expected cell < 5 → abstain). Probe on real fixture dim shapes (cost_center K=5 balanced, invoice status K=5 skewed, method K=4): family = 1-2 affected slices holding ≥10% of rows, conditional rate 0.2-0.6 vs base ≤0.05 → min **0.129** / p05 0.178 / p50 0.42 vs MCAR adversary max **0.063** (margin +0.065, family min ≈ 2× adversary max). Small-slice inflation (V hit 0.38 uncorrected/unguarded) is fully absorbed by Cochran abstention. Time-confounded missingness scores ~0.27-0.31 — TRUE association whose root cause is time; context, not a false positive. Implementation: `stats.cramers_v` (engine + eval, pinned both sides), `SliceConditionalNullDetector` (value/NULLS, column-scoped, declared under the `statistics` phase → add_source detect; slice dims = sibling low-card categoricals, actual scanned distinct is the 2..50 gate, conditions only on slice-labelled rows). Gate pinned in `calibration/unit/test_slice_null_gate.py`; recall via `detection-slice-null-v1` (ordering grammar). | document the conditional-missingness rule (the `documented_dependency` archetype — reuses the `expected_dependency` overlay; teach closure in `test_teach_cycle.py`) / fix the slice's ingestion |
| **benford** | leading-digit anomaly → fabrication/rounding | **yes** (forensic context; current injection is weak) | **KL** surprise or **Nigrini MAD** | document expected pattern |
| **relationship_entropy** | orphan rate → join safety | **yes** | raw **orphan rate** (drop sqrt-boost) | fix FK / teach |
| **join_path_determinism** | ambiguous join paths → join safety | **yes** | **confidence-gated** candidate count (fix the over-fire) | pick the FK |
| **business_meaning** | garbage column names → interpretability | **yes** | LLM confidence → **pooling** (DAT-446) | name the column |
| **unit_entropy** | undeclared/ambiguous units → aggregation correctness | **yes** | declaration completeness → **pooling** (DAT-428) | declare the unit |
| **temporal_entropy** | broken time-role (unparseable dates) → time filtering | **yes** | type/role mismatch | re-type |
| **cross_table_consistency** | cross-table reconciliation breaks → correctness | **yes** | orphan / violation **rate** | fix / teach |
| **temporal_drift** | distribution shifted over time | **CUT** (DAT-442 reset) — meaningful only for **stationary / point-in-time** columns; transaction **flows** naturally vary (clean KS ≈ injected ≈ 0.53), so absolute drift can't separate a shift from noise. Real drift → DAT-445's **expected-variation** model. Proven: `calibration/unit/test_drift_recorded.py`. | two-sample **KS** / **PSI** vs an **expected-variation reference** | document expected seasonality |
| **slice_variance** (= "slices disagree about a measure") | column behaves differently across slices | **CUT** (DAT-442 reset; re-opened + re-cut DAT-519, 2026-06-15) — a between-slice k-sample test is structurally **blind to the slice-GLOBAL injections** the eval creates (Δη² ≈ 0.00 vs clean) and **saturates on legitimate cross-slice heterogeneity** of real financial data (clean η² ≈ 0.78). No grounded statistic rescues it; the old max-of-spreads fired only on non-injected columns. **DAT-519** added the one untested candidate — the **slice-pooling conflict C** (size-weighted JSD of per-slice value distributions vs the pooled mixture, slices-as-witnesses) — to the SAME scenarios: it joins η²/KW at the wall (global-injection blind: C 0.025→0.012; saturates on clean heterogeneity C=0.848; and an *injected* slice shift is **statistically identical** to a *naturally* different slice — η² 0.476 vs 0.474, C 0.297 vs 0.296). C is if anything worse (all-moment, so more saturated). The deep reason: between-slice disagreement of a MEASURE *is* the clean baseline, so it can never separate anomaly from structure. **The gateable shape is a per-slice INVARIANT RESIDUAL** (a relation that HOLDS in clean data → baseline of agreement ≈ 0, broken in one slice): probe [D] separated +0.968 (clean max residual 0.005 vs broken 0.974). That is exactly what the survivors do — `slice_conditional_null` (null-rate MCAR-flat → Cramér's V) and `temporal_behavior`'s DAT-491 reconciliation (Σevents≈Δstock). So a real "dimensional entropy" detector must be invariant-residual shaped with a **slice-conditional** injection family, NOT measure-disagreement. Proven: `calibration/unit/test_slice_variance_recorded.py` (η²/KW); DAT-519 probe (C + reframing, deleted — verdict here). | **Kruskal–Wallis** / ANOVA **η²** / slice-pooling **conflict C** (all insufficient) → per-slice **invariant residual** | document segmentation |
| **outlier_rate** | extreme-value fraction → aggregation risk | **CUT** (DAT-442 reset) — absolute single-column IQR/z-score has **no setting that separates** an injected burst from clean financial heavy tails: shape-adapted **log-IQR absorbs** a 5%@10x burst (clean ≈ injected ≈ 0.003), while **linear IQR flags 25%+** of legitimate long-tail values (54 columns ≥ 0.20 on one run). The old piecewise map inflated a linear-IQR artifact. Same wall as temporal_drift / slice_variance. Redesign would need **D_KL(observed‖reference)** vs an expected-variation model (cf. DAT-445), not chosen. Proven: `calibration/unit/test_outlier_rate_recorded.py`. | **IQR/MAD rate** (insufficient) → distributional **surprise** vs reference | document expected range |
| **unit_consistency (bimodality)** | scale mix within a column (kEUR among EUR) → aggregation correctness | **CUT** (DAT-428/442, engine `142e12cc`) — log10-magnitude **bimodality cannot separate** a scale mix from natural financial spread: clean `invoices.amount` already spans exponents 2→4 (BC = 0.559 ≈ the uniform pivot 0.555); a **×1000 mix at 29%** shifts values **contiguously** onto the clean tail → a wider unimodal smear, BC 0.598, margin < 0.05. Power-of-ten shifts preserve the mantissa (**Benford-blind**). The detector shell was built and deleted the same day. (Probe deleted — verdict recorded here.) Restart path: **cross-column magnitude ratios** among same-concept columns vs **ontology expected-unit** (needs a scale-mix family + `/ground`). `unit_entropy` (declaration completeness, teach-closable) survives as the U-half. | Pearson **bimodality coefficient** (insufficient) | declare the unit (`unit` teach — built, e2e-proven) |
| **stock/flow trajectory signature** | infer stock-vs-flow from the value SERIES alone → aggregation correctness | **CUT** (DAT-459, kill gate) — the **persistence signature conflates stochastic structure with stock/flow semantics**: a mean-reverting stock reads as a flow, a trending flow reads as a stock, small-n period counts starve the estimator, and on materialized cumulatives the test is tautological. Falsified by the mean-reverting-stock / trending-flow / noisy-stock / small-n / tautology probes (probes deleted; verdict here). The surviving DATA witness is DAT-491's **structural reconciliation** — per-period sums vs deltas over the slice substrate reads the accounting IDENTITY, not the trajectory — pooled into `temporal_behavior` below. | **ρ₁ / variance-ratio** persistence (insufficient) | n/a — never shipped |
| **temporal_behavior (stock/flow)** | summing a stock across periods is silently wrong — is each measure a point-in-time level or a per-period movement? | **yes** | pooling **C/U** over three witnesses: **ontology prior** + **LLM claim** (r measured 0.762/0.838 over the generative stock/flow corpus, clear + ambiguous strata, DAT-450 rig) + **structural reconciliation** (DAT-491; r = 0.889 measured over the events-backed corpus `detection-stockflow-events-v1`, DAT-450 rig). **Marginal value PROVEN (2026-06-16):** an A/B ablation on the resolved label (struct r 0.889→0.0) over the crossed corpus `detection-stockflow-events-ambiguous-v1` (event-backing × ambiguous names — the cell `events-v1` (clear names → redundant) and `cal-v1` (no backing → silent) each lacked) showed structural **rescues 2/5 backed×ambiguous columns** arm A gets right and arm B gets wrong (backed-only acc 88%→71%, Δ +16pp; 0 reverse flips; broken-backed `paid_payables` correctly does NOT override at match_rate 0.33). The witness is the decisive data-grounded tiebreaker, not redundant with the name pair → **KEEP** (do not de-materialize the slice→temporal→lineage substrate). Recall/precision/teach-closure proven e2e 2026-06-10 (`calibration/detector_coverage.yaml`). | log-linear pooling **C/U**; reconciliation **match rate** | `concept_property` teach (e2e-proven: C 0.305 → 0.007) |
| **dimensional_entropy** | cross-column dependency (mutual exclusivity, …) | **DEMOTED off the loss path (2026-06-16; engine branch `refactor/dimensional-entropy-demote-loss`, PR pending) → informative DirectSignal, benford lane.** It WAS on the loss path (loss.yaml:163, query 0.3 / agg 0.4), so its bands had to predict WRONG ANSWERS, not association — but a Tier-1 kill-gate probe (engine `stats.nmi`; probe deleted — verdict here) falsifies that in two ways, both pure-math-robust: (1) **blind to the violation that causes the wrong answer** — a 5%-broken zip→city FD (the bad-join signal) barely moves NMI (clean 0.862 → 0.799, same `investigate` agg band); the *violation rate* is owned by `derived_value`/`relationship_entropy`/orphan_rate, not NMI. (2) **The band is monotone the WRONG way** — worse data → lower NMI → *readier* band: clean mutex/alias/FD (NMI 1.0/1.0/0.862, NO wrong answer) all band `agg=investigate`, while a 20%-violated FD (NMI 0.608, worst wrong answer) bands `agg=ready`. A loss signal highest on safe data and lowest on unsafe data is anti-predictive — the **benford/DEMOTE signature** (loss.yaml:65 "INFORMATIVE SIGNAL, not tunable entropy"): keep the NMI score + `expected_dependency` teach as a DirectSignal, remove the loss row so it stops driving bands. Also: the detector is **table-grained** (one `table:` object = max NMI over pairs), and the "g3 FD pass" that could rescue a hierarchy role **does not exist** (NMI is symmetric — no direction). Full e2e corpus (`detection-dependency-v1`, per-stratum tables) deferred; the math says it would confirm, not overturn. | normalized **mutual information** | document the rule (`expected_dependency`) |
| **dimension_coverage** | fact-table dimension completeness | **review** | coverage ratio | teach |
| **business_cycle_health** | business-cycle anomaly | **review** | (define) | teach |

## Rollout

1. **Capture the recorded fixture** (`scripts/capture_fixture.py` → `calibration/fixtures/entropy_inputs.sqlite`). One live run; docker once.
2. **Build the Tier-1/2 harness** — fixture loaders + assertion helpers (ordering, calibration, teach-closure) that need no docker.
3. **Per-measurement, purpose-first:** write the contract entry, then the Tier-1 unit (synthetic) + Tier-2 (recorded) tests, then the statistic. Cut / reframe the **conditional** rows honestly.
4. **Tier 3** becomes the milestone gate: the existing calibration suite, run when Tier 1/2 are green — proving wiring, not math.

## How to run

```bash
# Tier 1 + 2 — the dev loop (milliseconds, no docker):
uv run pytest calibration/unit -q              # synthetic + recorded-fixture tests

# Refresh the recorded fixture (only when pipeline output shape changes):
python scripts/capture_fixture.py              # docker stack up; one pipeline run

# Tier 3 — milestone gate (minutes, docker):
make calibrate                                  # full generate → pipeline → suite
```
