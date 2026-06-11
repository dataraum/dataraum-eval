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

## Measurement catalog

The grounded statistic per measurement, and the honest "earns its place" call. The
**conditional / cut** rows are where the reset pays off — purpose-first kills or
reframes measurements that only ever produced noise.

| Measurement | Purpose / context it serves | Earns it? | Grounded statistic | Fix / teach |
|---|---|---|---|---|
| **null_semantics** | "is `#ERR` a null?" — don't silently aggregate contested markers | **yes** | pooling **C/U** over witnesses | null_value overlay → witness flips |
| **type_fidelity** | type-cast failures → structural trust | **yes** | raw quarantine **rate** (drop `_boost_rate`) | re-type / teach pattern |
| **null_ratio** | missing fraction → completeness | **yes** | raw **rate** | fill / document |
| **slice-conditional null (DAT-473)** | nulls concentrated in specific slices — dataset-level null_ratio hides a 60%-null slice behind a 5% overall rate, silently biasing that slice's aggregates | **BUILD** (kill gate passed 2026-06-11; implementation pending — needs the testdata family + engine detector) | bias-corrected **Cramér's V** (Bergsma) on the 2×K is-null × slice table under the **Cochran validity rule** (any expected cell < 5 → abstain). Probe on real fixture dim shapes (cost_center K=5 balanced, invoice status K=5 skewed, method K=4): family = 1-2 affected slices holding ≥10% of rows, conditional rate 0.2-0.6 vs base ≤0.05 → min **0.129** / p05 0.178 / p50 0.42 vs MCAR adversary max **0.063** (margin +0.065, family min ≈ 2× adversary max). Small-slice inflation (V hit 0.38 uncorrected/unguarded) is fully absorbed by Cochran abstention. Time-confounded missingness scores ~0.27-0.31 — TRUE association whose root cause is time; context, not a false positive. Known gap: the recorded fixture has no real nullable×(K≥2) dim pair — the family injection must create one. Gate pinned in `calibration/unit/test_slice_null_gate.py`. | document the conditional-missingness rule (the `documented_dependency` archetype) / fix the slice's ingestion |
| **benford** | leading-digit anomaly → fabrication/rounding | **yes** (forensic context; current injection is weak) | **KL** surprise or **Nigrini MAD** | document expected pattern |
| **relationship_entropy** | orphan rate → join safety | **yes** | raw **orphan rate** (drop sqrt-boost) | fix FK / teach |
| **join_path_determinism** | ambiguous join paths → join safety | **yes** | **confidence-gated** candidate count (fix the over-fire) | pick the FK |
| **business_meaning** | garbage column names → interpretability | **yes** | LLM confidence → **pooling** (DAT-446) | name the column |
| **unit_entropy** | undeclared/ambiguous units → aggregation correctness | **yes** | declaration completeness → **pooling** (DAT-428) | declare the unit |
| **temporal_entropy** | broken time-role (unparseable dates) → time filtering | **yes** | type/role mismatch | re-type |
| **cross_table_consistency** | cross-table reconciliation breaks → correctness | **yes** | orphan / violation **rate** | fix / teach |
| **temporal_drift** | distribution shifted over time | **CUT** (DAT-442 reset) — meaningful only for **stationary / point-in-time** columns; transaction **flows** naturally vary (clean KS ≈ injected ≈ 0.53), so absolute drift can't separate a shift from noise. Real drift → DAT-445's **expected-variation** model. Proven: `calibration/unit/test_drift_recorded.py`. | two-sample **KS** / **PSI** vs an **expected-variation reference** | document expected seasonality |
| **slice_variance** | column behaves differently across slices | **CUT** (DAT-442 reset) — a between-slice k-sample test is structurally **blind to the slice-GLOBAL injections** the eval creates (Δη² ≈ 0.00 vs clean) and **saturates on legitimate cross-slice heterogeneity** of real financial data (clean η² ≈ 0.78). No grounded statistic rescues it; the old max-of-spreads fired only on non-injected columns. The one defensible sliver (null-rate-across-slices) is a proportions test (**Cramér's V**), deferred to DAT-184 + a slice-conditional-null injection. Proven: `calibration/unit/test_slice_variance_recorded.py`. | **Kruskal–Wallis** / ANOVA **η²** (insufficient) | document segmentation |
| **outlier_rate** | extreme-value fraction → aggregation risk | **CUT** (DAT-442 reset) — absolute single-column IQR/z-score has **no setting that separates** an injected burst from clean financial heavy tails: shape-adapted **log-IQR absorbs** a 5%@10x burst (clean ≈ injected ≈ 0.003), while **linear IQR flags 25%+** of legitimate long-tail values (54 columns ≥ 0.20 on one run). The old piecewise map inflated a linear-IQR artifact. Same wall as temporal_drift / slice_variance. Redesign would need **D_KL(observed‖reference)** vs an expected-variation model (cf. DAT-445), not chosen. Proven: `calibration/unit/test_outlier_rate_recorded.py`. | **IQR/MAD rate** (insufficient) → distributional **surprise** vs reference | document expected range |
| **unit_consistency (bimodality)** | scale mix within a column (kEUR among EUR) → aggregation correctness | **CUT** (DAT-428/442, engine `142e12cc`) — log10-magnitude **bimodality cannot separate** a scale mix from natural financial spread: clean `invoices.amount` already spans exponents 2→4 (BC = 0.559 ≈ the uniform pivot 0.555); a **×1000 mix at 29%** shifts values **contiguously** onto the clean tail → a wider unimodal smear, BC 0.598, margin < 0.05. Power-of-ten shifts preserve the mantissa (**Benford-blind**). The detector shell was built and deleted the same day. (Probe deleted — verdict recorded here.) Restart path: **cross-column magnitude ratios** among same-concept columns vs **ontology expected-unit** (needs a scale-mix family + `/ground`). `unit_entropy` (declaration completeness, teach-closable) survives as the U-half. | Pearson **bimodality coefficient** (insufficient) | declare the unit (`unit` teach — built, e2e-proven) |
| **stock/flow trajectory signature** | infer stock-vs-flow from the value SERIES alone → aggregation correctness | **CUT** (DAT-459, kill gate) — the **persistence signature conflates stochastic structure with stock/flow semantics**: a mean-reverting stock reads as a flow, a trending flow reads as a stock, small-n period counts starve the estimator, and on materialized cumulatives the test is tautological. Falsified by the mean-reverting-stock / trending-flow / noisy-stock / small-n / tautology probes (probes deleted; verdict here). The surviving DATA witness is DAT-491's **structural reconciliation** — per-period sums vs deltas over the slice substrate reads the accounting IDENTITY, not the trajectory — pooled into `temporal_behavior` below. | **ρ₁ / variance-ratio** persistence (insufficient) | n/a — never shipped |
| **temporal_behavior (stock/flow)** | summing a stock across periods is silently wrong — is each measure a point-in-time level or a per-period movement? | **yes** | pooling **C/U** over three witnesses: **ontology prior** + **LLM claim** (r measured 0.762/0.838 over the generative stock/flow corpus, clear + ambiguous strata, DAT-450 rig) + **structural reconciliation** (DAT-491; r = 0.85 probe-derived placeholder until an events-backed family lets the rig measure it). Recall/precision/teach-closure proven e2e 2026-06-10 (`calibration/detector_coverage.yaml`). | log-linear pooling **C/U**; reconciliation **match rate** | `concept_property` teach (e2e-proven: C 0.305 → 0.007) |
| **dimensional_entropy** | cross-column dependency (mutual exclusivity, …) | **conditional** — context for "these columns aren't independent." Earns it only if a downstream decision uses it. | normalized **mutual information** | document the rule |
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
